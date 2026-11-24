"""The dataset cache root is resolved at call time, so a read-only home can be moved (#1261).

``AGENTDESCENT_CACHE`` names the root itself; ``XDG_CACHE_HOME`` puts it under
``<XDG_CACHE_HOME>/agentdescent``; with neither set the root is exactly what it
has always been, ``~/.cache/agentdescent``.
"""

import os

from agentdescent import dataloader as dl


def test_agentdescent_cache_sets_the_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    path = dl.cache_path("gsm8k", "x.jsonl")

    assert path == str(tmp_path / "cache" / "gsm8k" / "x.jsonl")
    assert os.path.isdir(os.path.dirname(path))


def test_xdg_cache_home_puts_the_root_under_agentdescent(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    path = dl.cache_path("gsm8k", "x.jsonl")

    assert path == str(tmp_path / "xdg" / "agentdescent" / "gsm8k" / "x.jsonl")
    assert os.path.isdir(os.path.dirname(path))


def test_agentdescent_cache_wins_over_xdg_cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_CACHE", str(tmp_path / "explicit"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))

    path = dl.cache_path("gsm8k", "x.jsonl")

    assert path == str(tmp_path / "explicit" / "gsm8k" / "x.jsonl")


def test_without_the_variables_the_root_is_todays_default(monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_CACHE", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)

    # ``cache_path`` would create this directory, which on a host with a
    # read-only home is exactly today's OSError (the bug in #1261): assert the
    # resolved root instead of provoking the failure again.
    assert dl._cache_root() == os.path.expanduser("~/.cache/agentdescent")
