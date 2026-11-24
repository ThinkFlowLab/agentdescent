"""The workflow files the guards read, on both suffixes.

GitHub runs a file under ``.github/workflows`` whose name ends in ``.yml`` or
``.yaml``.  The guards used to glob ``*.yml`` only, so a workflow committed as
``tests.yaml`` carried no ``timeout-minutes`` and no pinned ``uses:`` while every
guard kept passing -- measured at main ``441ac2bd``: with such a file in the
tree, ``test_workflow_job_timeouts.py`` and ``test_workflow_actions_pinned.py``
were green.  One list, both suffixes, so the next reader cannot narrow it again.
"""

from pathlib import Path

# GitHub's own two spellings, in the order the guards should read them.
SUFFIXES = (".yml", ".yaml")


def workflow_files(root):
    """Every workflow file under ``root/.github/workflows``, sorted by name."""
    directory = Path(root) / ".github" / "workflows"
    return sorted(path for suffix in SUFFIXES for path in directory.glob(f"*{suffix}"))
