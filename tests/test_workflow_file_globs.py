"""The workflow guards read every workflow file, on both suffixes.

GitHub runs a file under ``.github/workflows`` whose name ends in ``.yml`` **or**
``.yaml``, but the guards used to glob ``*.yml`` only: a workflow committed as
``tests.yaml`` would carry no ``timeout-minutes`` and no pinned ``uses:``, and
both guards would still pass.  The hole is latent today -- all eight files in
the directory are ``.yml`` -- which is exactly why nothing caught it: the guard
only goes red once the file it cannot see already exists.

These rows hold the enumeration itself, so the guard cannot quietly narrow back
to one suffix: one fixture directory with both suffixes, and one check that each
guard's own file list is the shared helper's list.
"""

import importlib

import pytest

from tests._workflows import workflow_files


def _tree(root, *names):
    """A ``.github/workflows`` directory holding ``names``."""
    directory = root / ".github" / "workflows"
    directory.mkdir(parents=True)
    for name in names:
        (directory / name).write_text(
            "on: push\njobs:\n  only:\n    runs-on: ubuntu-latest\n"
            "    steps:\n      - run: true\n",
            encoding="utf-8",
        )
    return directory


def test_both_suffixes_are_enumerated(tmp_path):
    _tree(tmp_path, "ci.yml", "pages.yaml")
    assert [p.name for p in workflow_files(tmp_path)] == ["ci.yml", "pages.yaml"]


def test_other_files_in_the_directory_are_ignored(tmp_path):
    _tree(tmp_path, "ci.yml", "ci.yml.bak", "notes.md", "README")
    assert [p.name for p in workflow_files(tmp_path)] == ["ci.yml"]


def test_an_empty_directory_enumerates_nothing(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    assert workflow_files(tmp_path) == []


@pytest.mark.parametrize(
    "module",
    [
        "tests.test_workflow_job_timeouts",
        "tests.test_workflow_actions_pinned",
        "tests.test_process_controller",
    ],
)
def test_each_guard_reads_the_shared_list(module):
    """A guard that globs for itself drifts the moment a suffix is added."""
    guard = importlib.import_module(module)
    root = guard.ROOT
    assert [p.name for p in guard.WORKFLOWS] == [
        p.name for p in workflow_files(root)
    ], f"{module} does not enumerate both .yml and .yaml workflow files"
    assert all(p.suffix in (".yml", ".yaml") for p in guard.WORKFLOWS)
