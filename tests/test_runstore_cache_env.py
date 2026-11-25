"""The detached child inherits the launcher's cache root, so both name one tree (#1280).

``runstore.launch`` scrubs the environment but deliberately keeps
``AGENTDESCENT_*`` and starts the child with ``cwd=rd.path``. A relative
``AGENTDESCENT_CACHE`` -- or ``XDG_CACHE_HOME`` -- therefore names one tree in
the process that launched the run and another in the child: the dataset cache
moves with every run directory. Only the launcher still knows the cwd the
operator typed the value in, so it resolves both knobs before the value crosses
the detach boundary. Nothing here starts a real process.
"""

import os
import subprocess

import pytest

from agentdescent import dataloader as dl
from agentdescent import runstore

from tests.test_evolvespec import _dir_spec


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    return str(tmp_path / "runs")


def _launched_child_env(tmp_path, monkeypatch):
    """Run ``launch`` with a fake detach; return the env, cwd and run dir it used."""
    rd = runstore.create(_dir_spec(str(tmp_path)).to_dict(),
                         store=str(tmp_path / "runs"))
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        # A pid that cannot be alive on this machine, so no status here lies.
        return subprocess.CompletedProcess(argv, 0, stdout="2000000000\n",
                                           stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd)

    assert len(calls) == 1, calls
    _, kw = calls[0]
    assert kw["cwd"] == rd.path, "the child starts in the run directory"
    return kw["env"], rd


def test_relative_agentdescent_cache_reaches_the_child_absolute(store, tmp_path,
                                                                monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTDESCENT_CACHE", "rel-cache")
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    env, rd = _launched_child_env(tmp_path, monkeypatch)

    value = env["AGENTDESCENT_CACHE"]
    assert os.path.isabs(value), value
    assert value == str(tmp_path / "rel-cache")
    # Read where the child reads it: still the tree the operator meant.
    monkeypatch.chdir(rd.path)
    monkeypatch.setenv("AGENTDESCENT_CACHE", value)
    assert dl._cache_root() == str(tmp_path / "rel-cache")


def test_relative_xdg_cache_home_reaches_the_child_absolute(store, tmp_path,
                                                            monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTDESCENT_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", "rel-xdg")

    env, rd = _launched_child_env(tmp_path, monkeypatch)

    value = env["XDG_CACHE_HOME"]
    assert os.path.isabs(value), value
    assert value == str(tmp_path / "rel-xdg")
    monkeypatch.chdir(rd.path)
    monkeypatch.setenv("XDG_CACHE_HOME", value)
    assert dl._cache_root() == str(tmp_path / "rel-xdg" / "agentdescent")


def test_an_absolute_cache_root_is_forwarded_untouched(store, tmp_path, monkeypatch):
    root = tmp_path / "already" / "absolute"
    monkeypatch.setenv("AGENTDESCENT_CACHE", str(root))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    env, _ = _launched_child_env(tmp_path, monkeypatch)

    assert env["AGENTDESCENT_CACHE"] == str(root)
