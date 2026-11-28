"""Importing the candidate-method matrix must not build a port (#1260).

``bench/candidate_methods.py`` learns each port's ``name`` and its reserved
proposal-call count by calling ``build(0)``, and ``build`` loads a dataset. So
the matrix's own ``--help`` needed a writable dataset cache -- and, on a clean
cache, a download -- before it could print ``usage:``.

The table is metadata, not an observation: it belongs to the module that
declares the port, so importing the matrix has to work on a host whose cache is
read-only. These tests run in a fresh interpreter with ``cache_path`` raising
``OSError(30)``, and pin the whole table so a lazily-built one cannot quietly
drop a port or change a fidelity string.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: ``(name, fidelity)`` for every port in the matrix, as declared by the ports
#: at the commit that fixed #1260. Pinned whole: "the import works" is not the
#: same claim as "the matrix still has all fourteen ports".
PORTS = (
    ("absolute_zero", "inference_analogue"),
    ("aflow", "mechanism_microport"),
    ("agent0", "inference_analogue"),
    ("dynamic_cheatsheet", "mechanism_microport"),
    ("godel_agent", "self_edit_analogue"),
    ("gskill", "mechanism_microport"),
    ("promptbreeder", "mechanism_microport"),
    ("r_zero", "inference_analogue"),
    ("reflexion", "mechanism_microport"),
    ("self_refine", "mechanism_microport"),
    ("sica", "self_edit_analogue"),
    ("skillweaver", "environment_analogue"),
    ("textgrad", "mechanism_microport"),
    ("voyager", "environment_analogue"),
)

#: Reserved proposal calls per candidate, as declared by each port. Two for the
#: ports whose proposal is two model calls; one everywhere else.
PROPOSAL_CALLS = {
    "promptbreeder": 2,
    "aflow": 2,
    "r_zero": 2,
    "textgrad": 2,
}

#: The host this test stands in for: a read-only ``~/.cache``. Every dataset
#: read funnels through ``cache_path``, so patching it before the matrix is
#: imported is the narrowest version of that host -- any dataset load raises.
NO_CACHE = textwrap.dedent(
    """
    import agentdescent.dataloader as dataloader

    def _read_only(*args, **kwargs):
        raise OSError(30, "Read-only file system")

    dataloader.cache_path = _read_only
    """
)


def run(body: str) -> subprocess.CompletedProcess:
    """Run ``body`` in a fresh interpreter that cannot write a dataset cache.

    ``tests/conftest.py`` turns on the bundled sample for **both** domains and
    each switch returns before the cache -- so both have to go, or the three
    GSM-HARD ports (``reflexion``, ``self_refine``, ``sica``) would load their
    bundled sample and an import-time build of one of them would pass here
    without the dataset path being reached. Without them the child takes the
    path a reader's ``--help`` takes.
    """
    env = dict(os.environ)
    env.pop("AGENTDESCENT_GSM8K_SAMPLE", None)
    env.pop("AGENTDESCENT_GSMHARD_SAMPLE", None)
    script = NO_CACHE + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_the_name_table_imports_without_a_dataset_cache():
    proc = run(
        """
        import json

        import bench.candidate_methods as matrix

        print(json.dumps(sorted(matrix.ALGORITHMS)))
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout) == [name for name, _ in PORTS]


def test_the_fidelity_strings_still_come_from_the_ports():
    proc = run(
        """
        import json

        import bench.candidate_methods as matrix

        print(json.dumps(
            {name: fidelity for name, (fidelity, _) in matrix.ALGORITHMS.items()}
        ))
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout) == dict(PORTS)


def test_the_reserved_proposal_calls_match_every_port():
    proc = run(
        """
        import json

        from bench.candidate_methods import PROPOSAL_CALLS_PER_CANDIDATE as calls

        print(json.dumps(calls))
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout) == {
        name: PROPOSAL_CALLS.get(name, 1) for name, _ in PORTS
    }


def test_help_prints_usage_without_a_dataset_cache():
    proc = run(
        """
        import runpy
        import sys

        sys.argv = ["bench.candidate_methods", "--help"]
        runpy.run_module("bench.candidate_methods", run_name="__main__")
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("usage: "), proc.stdout


def test_the_stub_cache_is_actually_read_only():
    """The control: a hostile cache that does not bite would make the rest moot."""
    proc = run(
        """
        import agentdescent.dataloader as dataloader

        try:
            dataloader.cache_path("gsm8k", "train.jsonl")
        except OSError as exc:
            print("raised", exc.errno)
        """
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == "raised 30"
