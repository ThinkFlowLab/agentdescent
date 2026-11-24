"""The bench index is pinned to the tree, not to prose.

``docs/bench-index.md`` lists every ``bench/*.py`` module that can be run on its
own. Two dirs can drift in both directions: a new bench module with a
``__main__`` block lands without a row, and a row keeps describing a module that
was renamed or deleted. Both are docs bugs that only show up the next time
somebody tries to follow the page, so they are pinned here:

* the set of modules carrying ``if __name__ == "__main__"`` equals the set of
  modules whose row gives a ``python -m bench.<module>`` command;
* the page exists at all -- without it the subscription above would be an empty
  set matching an empty set.

The nav entry is not asserted here: ``tests/test_site_navigation.py`` already
fails for a page that is missing from ``mkdocs.yml``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = ROOT / "bench"
INDEX = ROOT / "docs" / "bench-index.md"

#: A row's command cell, e.g. ``python -m bench.long_horizon --steps 9``.
COMMAND_RE = re.compile(r"python -m bench\.([a-z0-9_]+)")


def _has_main(path: Path) -> bool:
    """True when the module has a top-level ``if __name__ == "__main__"`` block."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
            continue
        left, right = test.left, test.comparators[0]
        if (isinstance(left, ast.Name) and left.id == "__name__"
                and isinstance(right, ast.Constant) and right.value == "__main__"):
            return True
    return False


def runnable_modules() -> set[str]:
    """Every ``bench/*.py`` that can be invoked as ``python -m bench.<name>``."""
    return {path.stem for path in BENCH_DIR.glob("*.py") if _has_main(path)}


def listed_modules() -> set[str]:
    """Every module the index gives a runnable command for."""
    if not INDEX.is_file():
        return set()
    return set(COMMAND_RE.findall(INDEX.read_text(encoding="utf-8")))


def test_index_page_exists() -> None:
    assert INDEX.is_file(), (
        "docs/bench-index.md is missing: the bench tree has runnable modules "
        "and no page names them"
    )


def test_every_runnable_bench_module_has_a_row() -> None:
    missing = sorted(runnable_modules() - listed_modules())
    assert not missing, (
        "bench modules with a __main__ block but no row in docs/bench-index.md: "
        f"{missing}. Add a row (what it measures, command, offline or key-gated, "
        "evidence file) in the same change as the module."
    )


def test_every_row_names_a_runnable_module() -> None:
    stale = sorted(listed_modules() - runnable_modules())
    assert not stale, (
        "docs/bench-index.md lists modules that no longer run on their own: "
        f"{stale}. Drop the row or restore the __main__ block."
    )
