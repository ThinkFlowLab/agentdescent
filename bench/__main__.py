"""List the runnable `bench` modules, or run one of them.

`python -m bench` answers the discovery question in the terminal: which modules
under `bench/` can be executed and what each one measures. The set is read off
the package directory with `ast`, so listing imports no bench module and needs
no dataset cache — the point is to be usable before the heavy pieces work
(#1262). ``python -m bench <name> ...`` hands the arguments to that module.
"""

from __future__ import annotations

import ast
import runpy
import sys
from pathlib import Path

_PACKAGE = Path(__file__).resolve().parent


def _carries_main_guard(tree: ast.Module) -> bool:
    """True when the module would run under `python -m bench.<name>`."""
    return any(
        isinstance(node, ast.If) and "__main__" in ast.unparse(node.test)
        for node in tree.body
    )


def _runnable() -> list[tuple[str, str]]:
    """`(module name, first docstring line)` for every runnable module."""
    modules: list[tuple[str, str]] = []
    for path in sorted(_PACKAGE.glob("*.py")):
        if path.name.startswith("_"):
            continue  # `__init__` is the package, not a module to run
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not _carries_main_guard(tree):
            continue
        docstring = (ast.get_docstring(tree) or "").strip()
        summary = docstring.splitlines()[0].strip() if docstring else "(undocumented)"
        modules.append((path.stem, summary))
    return modules


def _print_listing(modules: list[tuple[str, str]], stream) -> None:
    print("Runnable bench modules — name: what it measures", file=stream)
    for name, summary in modules:
        print(f"{name}: {summary}", file=stream)
    print("Flags: python -m bench.<name> --help", file=stream)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    modules = _runnable()
    if not args or args[0] in ("-h", "--help"):
        _print_listing(modules, sys.stdout)
        return 0
    name, rest = args[0], args[1:]
    if name not in {module for module, _ in modules}:
        # Say what is missing, then what exists: a bare traceback sends the
        # reader back to the docs page for a list this command already knows.
        print(f"no bench module '{name}'", file=sys.stderr)
        _print_listing(modules, sys.stderr)
        return 2
    sys.argv = [sys.argv[0], *rest]
    runpy.run_module(f"bench.{name}", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
