"""Every in-repo ``path:line`` citation in the docs must land inside the file.

The pages checked here are reference pages whose stated value is that their
rows are the verified part, so a citation that runs past a file's last line
sends a reader to nothing. This guard walks ``docs/**/*.md`` and ``README.md``,
reads every backticked ``path:line`` or ``path:line-line`` citation, and
requires the cited file to exist, the line numbers to start at 1 and run
forward, the path to stay inside the checkout after resolving any symlink,
and the last cited line to be within that file's line count.

Citations into codebases this repository does not ship — the upstream
Elixir/DGM trees the port pages quote — are pinned in ``_EXTERNAL``. A pin is
allowed only while a page still quotes it at exactly those coordinates, so a
pin the page stopped citing is reported instead of staying permanently
allowed. Everything else is checked, so a deleted file or a new pointer that
resolves to nothing fails here instead of rotting quietly.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_CITATION = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9_]+):(\d+)(?:-(\d+))?`")

# (page, path, first line, last line or None) for citations into codebases this
# repository does not contain. Each entry names a file the page quotes from the
# upstream tree, not a file a reader can open in this checkout.
_EXTERNAL = {
    ("docs/algo-genesis.md", "agents/architect.ex", 23, None),
    ("docs/algo-genesis.md", "agents/executor.ex", 64, None),
    ("docs/algo-genesis.md", "agents/manager.ex", 58, None),
    ("docs/algo-genesis.md", "evolution.py", 2739, None),
    ("docs/algo-genesis.md", "runtime/genesis.ex", 152, None),
    ("docs/port-fidelity.md", "DGM_outer.py", 91, 100),
    ("docs/port-fidelity.md", "adapters/git.ex", 284, None),
    ("docs/port-fidelity.md", "agent/subagent_processing.ex", 527, None),
    ("docs/port-fidelity.md", "agents/manager.ex", 58, None),
    ("docs/port-fidelity.md", "agents/manager.ex", 179, None),
    ("docs/port-fidelity.md", "runtime/genesis.ex", 152, None),
}


def _pages(root: Path = REPO_ROOT) -> list[Path]:
    pages = sorted(root.glob("docs/**/*.md"))
    readme = root / "README.md"
    if readme.is_file():
        pages.append(readme)
    return pages


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _problems(root: Path = REPO_ROOT, external: set | None = None) -> list[str]:
    if external is None:
        external = _EXTERNAL
    problems: list[str] = []
    seen_external: set[tuple[str, str, int, int | None]] = set()
    for page in _pages(root):
        text = page.read_text(encoding="utf-8")
        rel_page = page.relative_to(root).as_posix()
        for match in _CITATION.finditer(text):
            path, first, last = match.group(1), int(match.group(2)), match.group(3)
            end = int(last) if last else first
            page_line = text.count("\n", 0, match.start()) + 1
            citation = f"{path}:{first}" + (f"-{last}" if last else "")
            prefix = f"{rel_page}:{page_line} -> {citation}"
            if ".." in Path(path).parts or Path(path).is_absolute():
                problems.append(f"{prefix} (citation path escapes this repository)")
                continue
            if first < 1 or end < first:
                problems.append(f"{prefix} (line numbers start at 1 and run forward)")
                continue
            target = root / path
            try:
                resolved = target.resolve()
                root_resolved = root.resolve()
            except (OSError, RuntimeError):
                problems.append(f"{prefix} (file does not exist)")
                continue
            if not resolved.is_relative_to(root_resolved):
                problems.append(f"{prefix} (citation path escapes this repository)")
                continue
            if resolved.is_file():
                count = _line_count(resolved)
                if end > count:
                    problems.append(f"{prefix} (file has {count} lines)")
            elif (rel_page, path, first, end if last else None) not in external:
                problems.append(f"{prefix} (file does not exist)")
            else:
                seen_external.add((rel_page, path, first, end if last else None))
    for page, path, first, last in sorted(external - seen_external, key=str):
        citation = f"{path}:{first}" + (f"-{last}" if last else "")
        problems.append(f"{page} -> {citation} (pinned in _EXTERNAL, no longer cited)")
    return problems


def _temp_tree(root: Path, pages: dict[str, str], files: dict[str, str]) -> None:
    for name, text in {**pages, **files}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_docs_citations_resolve_inside_their_files() -> None:
    problems = _problems()
    assert not problems, (
        f"{len(problems)} doc citation(s) do not resolve into this repository:\n"
        + "\n".join(problems)
    )


def test_a_stale_external_pin_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pin whose page stopped citing it must fail, not sit there allowed."""
    stale = ("docs/algo-genesis.md", "agents/nowhere.ex", 7, None)
    monkeypatch.setattr(
        sys.modules[__name__], "_EXTERNAL", _EXTERNAL | {stale}
    )
    problems = _problems()
    assert any(
        "docs/algo-genesis.md" in p and "agents/nowhere.ex:7" in p for p in problems
    ), problems


def test_a_zero_line_citation_is_rejected(tmp_path: Path) -> None:
    """`path:0` passes today because line 0 is never past a file's end.

    The pin set is empty here: ``_EXTERNAL`` names pages in the shipped docs, so
    walking a temp tree without it would report every real pin as stale and
    hide whether the zero-line check fired at all.
    """
    _temp_tree(
        tmp_path,
        {"docs/page.md": "See `pkg/mod.py:0` for the guard.\n"},
        {"pkg/mod.py": "one\ntwo\n"},
    )
    problems = _problems(tmp_path, external=set())
    assert len(problems) == 1, problems
    assert "pkg/mod.py:0" in problems[0] and "docs/page.md" in problems[0], problems


def test_a_citation_cannot_escape_the_repository(tmp_path: Path) -> None:
    """`../../outside.txt:1` resolves to a real file and is read today."""
    root = tmp_path / "nested" / "repo"
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    _temp_tree(root, {"docs/page.md": "See `../../outside.txt:1`.\n"}, {})
    problems = _problems(root, external=set())
    assert len(problems) == 1, problems
    assert "../../outside.txt:1" in problems[0] and "docs/page.md" in problems[0], (
        problems
    )


def test_an_absolute_citation_cannot_escape_the_repository(tmp_path: Path) -> None:
    """An absolute path makes ``root / path`` drop the root and read elsewhere.

    The target deliberately does not exist: citing a real file such as
    ``/etc/hostname`` would make the assertion depend on the runner, and the
    point is the wrong message, not a missing file.
    """
    _temp_tree(
        tmp_path,
        {"docs/page.md": "See `/nonexistent/outside.txt:1`.\n"},
        {},
    )
    problems = _problems(tmp_path, external=set())
    assert len(problems) == 1, problems
    assert "/nonexistent/outside.txt:1" in problems[0], problems
    assert "escapes this repository" in problems[0], problems

def test_a_symlink_citation_cannot_escape_the_repository(tmp_path: Path) -> None:
    """A committed symlink to an outside file is followed today.

    Lexical checks (``..``, absolute) do not see a link, so ``_line_count()``
    reads a file this checkout does not contain. An in-range citation then
    reports nothing, and the page reads as verified.
    """
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("one\ntwo\nthree\n", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    _temp_tree(root, {"docs/page.md": "see `link.txt:2`\n"}, {})
    problems = _problems(root, external=set())
    assert len(problems) == 1, problems
    assert "link.txt:2" in problems[0] and "docs/page.md" in problems[0], problems
    assert "escapes this repository" in problems[0], problems


def test_a_symlink_citation_past_the_end_is_an_escape(tmp_path: Path) -> None:
    """Past-the-end through a link must not report the outside file's length."""
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("one\ntwo\nthree\n", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    _temp_tree(root, {"docs/page.md": "see `link.txt:9`\n"}, {})
    problems = _problems(root, external=set())
    assert len(problems) == 1, problems
    assert "link.txt:9" in problems[0] and "docs/page.md" in problems[0], problems
    assert "escapes this repository" in problems[0], problems
    assert "file has 3 lines" not in problems[0], problems
