"""`python -m bench` lists the modules the package can actually run.

The set is derived twice here, from the files themselves, so a module that
gains or loses a `__main__` guard fails this test until the listing follows.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO_ROOT / "bench"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bench", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )


def _runnable_modules() -> set[str]:
    """The modules under `bench/` that define a `__main__` entry themselves."""
    names: set[str] = set()
    for path in BENCH_DIR.glob("*.py"):
        if path.name.startswith("_"):
            continue  # the package and the entry point are not modules to run
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
                names.add(path.stem)
                break
    return names


def _listed_lines(output: str) -> list[str]:
    """The `name: what it measures` lines, without the header and the footer."""
    return [line for line in output.splitlines() if line and not line.startswith(("Runnable", "Flags:"))]


def test_listing_prints_every_runnable_module() -> None:
    result = _run()
    assert result.returncode == 0, f"exit {result.returncode}, stderr: {result.stderr}"
    assert result.stderr == "", result.stderr
    listed = {line.split(":", 1)[0] for line in _listed_lines(result.stdout)}
    assert listed == _runnable_modules()


def test_listing_says_what_each_module_measures() -> None:
    result = _run()
    assert result.returncode == 0, result.stderr
    for line in _listed_lines(result.stdout):
        name, _, description = line.partition(":")
        assert description.strip(), f"{name} is listed without saying what it measures"
    assert "python -m bench.<name> --help" in result.stdout


def test_listing_imports_no_bench_module() -> None:
    probe = "\n".join(
        [
            "import contextlib, io, sys",
            "import bench.__main__ as entry",
            "with contextlib.redirect_stdout(io.StringIO()):",
            "    rc = entry.main([])",
            "mods = sorted(m for m in sys.modules if m == 'bench' or m.startswith('bench.'))",
            "print(rc)",
            "print(' '.join(mods))",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "0", result.stdout
    assert lines[1] == "bench bench.__main__", lines[1]


def test_unknown_module_exits_2_and_names_the_list() -> None:
    result = _run("nope")
    output = result.stdout + result.stderr
    assert result.returncode == 2, f"exit {result.returncode}: {output}"
    assert "no bench module 'nope'" in output, output
    for name in _runnable_modules():
        assert name in output, f"{name} missing from the refusal"


def test_known_module_is_dispatched() -> None:
    result = _run("long_horizon", "--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
