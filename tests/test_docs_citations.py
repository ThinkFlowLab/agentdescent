"""Every in-repo ``path:line`` citation in the docs must land inside the file.

The pages checked here are reference pages whose stated value is that their
rows are the verified part, so a citation that runs past a file's last line
sends a reader to nothing. This guard walks ``docs/**/*.md`` and ``README.md``,
reads every backticked ``path:line`` or ``path:line-line`` citation, and
requires the cited file to exist and the last cited line to be within that
file's line count.

Citations into codebases this repository does not ship — the upstream
Elixir/DGM trees the port pages quote — are pinned in ``_EXTERNAL``. Everything
else is checked, so a deleted file or a new pointer that resolves to nothing
fails here instead of rotting quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

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


def _pages() -> list[Path]:
    pages = sorted(REPO_ROOT.glob("docs/**/*.md"))
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        pages.append(readme)
    return pages


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="replace").splitlines())


def _problems() -> list[str]:
    problems: list[str] = []
    for page in _pages():
        text = page.read_text(encoding="utf-8")
        rel_page = page.relative_to(REPO_ROOT).as_posix()
        for match in _CITATION.finditer(text):
            path, first, last = match.group(1), int(match.group(2)), match.group(3)
            end = int(last) if last else first
            page_line = text.count("\n", 0, match.start()) + 1
            citation = f"{path}:{first}" + (f"-{last}" if last else "")
            prefix = f"{rel_page}:{page_line} -> {citation}"
            target = REPO_ROOT / path
            if target.is_file():
                count = _line_count(target)
                if end > count:
                    problems.append(f"{prefix} (file has {count} lines)")
            elif (rel_page, path, first, end if last else None) not in _EXTERNAL:
                problems.append(f"{prefix} (file does not exist)")
    return problems


def test_docs_citations_resolve_inside_their_files() -> None:
    problems = _problems()
    assert not problems, (
        f"{len(problems)} doc citation(s) do not resolve into this repository:\n"
        + "\n".join(problems)
    )
