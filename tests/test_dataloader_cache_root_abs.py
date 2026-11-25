"""The dataset cache root is absolute, so the run's cache does not move with a cwd (#1280).

A run is written by one process and executed by another: the detached child
starts in the run directory (``runstore`` launches it with ``cwd=rd.path``), so
a relative ``AGENTDESCENT_CACHE`` or ``XDG_CACHE_HOME`` names a different tree
in each process. ``#402``/``#403`` already normalised the store base with
``abspath(expanduser(...))`` for exactly this reason; this is the dataset cache
catching up, with the default ``CACHE_ROOT`` left byte-identical.
"""

import inspect
import os

from agentdescent import dataloader as dl


def test_relative_agentdescent_cache_resolves_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTDESCENT_CACHE", "rel-cache")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    root = dl._cache_root()

    assert os.path.isabs(root), root
    assert root == str(tmp_path / "rel-cache")
    path = dl.cache_path("gsm8k", "x.jsonl")
    assert os.path.isabs(path), path
    assert path == str(tmp_path / "rel-cache" / "gsm8k" / "x.jsonl")


def test_relative_xdg_cache_home_resolves_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTDESCENT_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "rel-xdg")

    root = dl._cache_root()

    assert os.path.isabs(root), root
    assert root == str(tmp_path / "rel-xdg" / "agentdescent")
    path = dl.cache_path("gsm8k", "x.jsonl")
    assert os.path.isabs(path), path
    assert path == str(tmp_path / "rel-xdg" / "agentdescent" / "gsm8k" / "x.jsonl")


def test_relative_root_is_absolute_whatever_the_cwd(tmp_path, monkeypatch):
    """Whichever process resolves it -- the CLI or the detached child in the run dir.

    The value is still resolved against the cwd of the process that reads it
    (the same contract ``#403`` gave the run store), so the path is absolute in
    both, and ``cache_path`` never hands back a bare relative path.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setenv("AGENTDESCENT_CACHE", "rel-cache")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    monkeypatch.chdir(tmp_path)          # the process that starts the run
    started_from = dl._cache_root()
    assert os.path.isabs(started_from)
    assert started_from == str(tmp_path / "rel-cache")

    monkeypatch.chdir(run_dir)           # the detached child's cwd
    in_child = dl._cache_root()
    assert os.path.isabs(in_child)
    assert in_child == str(run_dir / "rel-cache")
    assert os.path.isabs(dl.cache_path("gsm8k", "x.jsonl"))


def test_without_the_variables_the_root_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(dl, "CACHE_ROOT", str(tmp_path / "default"))

    assert dl._cache_root() == str(tmp_path / "default")


def test_modelscope_docstring_names_the_knobs():
    doc = inspect.getdoc(dl.hf_rows_modelscope) or ""

    assert "AGENTDESCENT_CACHE" in doc
    assert "XDG_CACHE_HOME" in doc
    assert "~/.cache/agentdescent/modelscope/" not in doc
