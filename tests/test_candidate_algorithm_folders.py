"""An ALGORITHMS key must name a real examples folder, and the dry-run
reservation must match the policy each port actually builds.

source_fingerprint globs examples/<key>/*.py. A key that names no
directory would contribute no paths and no error, so editing that port
would stop changing the fingerprint. The first tests fail that mutation
from the filesystem alone. The reservation test compares
PROPOSAL_CALLS_PER_CANDIDATE to builder(0), so a literal that drifts
from the policy fails here too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bench.candidate_methods import (
    ALGORITHMS,
    PROPOSAL_CALLS_PER_CANDIDATE,
    algorithm_source_dir,
    source_fingerprint,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def test_algorithm_source_dir_refuses_a_key_that_names_no_folder(tmp_path):
    with pytest.raises(FileNotFoundError, match="names no folder"):
        algorithm_source_dir("missing-port", examples_dir=tmp_path)


def test_algorithm_source_dir_returns_an_existing_folder(tmp_path):
    folder = tmp_path / "promptbreeder"
    folder.mkdir()
    assert algorithm_source_dir("promptbreeder", examples_dir=tmp_path) == folder


def test_every_algorithm_key_names_an_examples_folder():
    for name in ALGORITHMS:
        path = algorithm_source_dir(name)
        assert path.is_dir(), name
        assert path == EXAMPLES_DIR / name


def test_source_fingerprint_refuses_a_key_that_names_no_folder(monkeypatch):
    monkeypatch.setitem(
        ALGORITHMS, "missing-port", ("mechanism_microport", lambda seed: None)
    )
    with pytest.raises(FileNotFoundError, match="names no folder"):
        source_fingerprint()


def test_proposal_calls_constant_matches_each_policy():
    for name, (_, builder) in ALGORITHMS.items():
        assert PROPOSAL_CALLS_PER_CANDIDATE[name] == (
            builder(0).proposal_calls_per_candidate
        ), name
