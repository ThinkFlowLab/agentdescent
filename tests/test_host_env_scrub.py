"""A detached run does not inherit the host session's identity or MCP config (#1082).

The worker's own gates run under an allowlist (:func:`runners._child_env`), but
the run `launch` detaches is our process, so it needs the API keys and PATH the
allowlist would drop. The cure is a denylist -- ``SESSION_MARKERS``, the same
tuple the candidate worker drops -- so `DSH_*`, `CLAUDE*`, `CODEX*`, `MCP_*`,
the OpenCode config carriers and `XDG_CONFIG_HOME` stay with the host, and
everything else, including the credentials the run needs, is passed through.

The parametrised row is the one that cannot go stale: it walks the tuple itself,
so a marker added for a new host is covered here the day it is added.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from agentdescent import runstore
from agentdescent.agents import SESSION_MARKERS as AGENTS_SESSION_MARKERS
from agentdescent.surface_common import SESSION_MARKERS, scrub_host_env

HOST_MARKERS = {
    "DSH_SESSION_ID": "host-session",
    "DSH_WORKSPACE": "/host/workspace",
    "CLAUDE_CODE_ENTRYPOINT": "cli",
    "CLAUDECODE": "1",
    "CODEX_SANDBOX": "1",
    "MCP_SERVERS": '{"filesystem": {}}',
}

#: One variable per marker, spelled the way a host would set it: the bare name
#: when the marker ends in ``_`` (``CLAUDECODE``), a suffixed one otherwise.
def _host_variable(marker: str) -> str:
    return marker if marker.endswith("_") else marker + "_PROBE"


def test_scrub_drops_host_markers_and_keeps_what_the_run_needs(monkeypatch):
    for name, value in HOST_MARKERS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("ARK_API_KEY", "not-a-real-key")

    env = scrub_host_env(os.environ)

    assert [k for k in env if k.upper().startswith(("DSH_", "CLAUDE", "CODEX", "MCP_"))] == []
    assert env["ARK_API_KEY"] == "not-a-real-key"
    assert env["PATH"] == os.environ["PATH"]


def test_scrub_does_not_mutate_the_caller(monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ID", "host-session")

    env = scrub_host_env(os.environ)

    assert env is not os.environ
    assert os.environ["DSH_SESSION_ID"] == "host-session"


def test_launch_hands_the_child_a_scrubbed_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DSH_SESSION_ID", "host-session")
    monkeypatch.setenv("MCP_SERVERS", '{"filesystem": {}}')
    monkeypatch.setenv("ARK_API_KEY", "not-a-real-key")
    rd = runstore.create({"kind": "text", "target": str(tmp_path / "out.md")},
                         store=str(tmp_path / "store"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)

    st = runstore.launch(rd)

    assert st.pid == 4242
    env = seen["env"]
    assert "DSH_SESSION_ID" not in env and "MCP_SERVERS" not in env
    assert env["ARK_API_KEY"] == "not-a-real-key"
    assert env["PYTHONPATH"]  # the launcher still makes the package importable


@pytest.mark.parametrize("marker", SESSION_MARKERS)
def test_every_session_marker_is_dropped(marker):
    """A marker added for a new host is covered without a second list (#1082).

    The scrub used to carry its own four prefixes, so five of these eleven
    crossed it; this row walks the tuple instead of naming them.
    """
    env = scrub_host_env({_host_variable(marker): "host-session", "PATH": "/bin"})

    assert [name for name in env if name != "PATH"] == []
    assert env["PATH"] == "/bin"


def test_the_worker_and_the_detached_run_share_one_list():
    """The two consumers of the denylist cannot drift apart again (#1082)."""
    assert AGENTS_SESSION_MARKERS is SESSION_MARKERS


def test_a_provider_key_that_merely_looks_like_a_marker_is_kept():
    """``OPENCODE_API_KEY`` is a credential, not a config pointer (#1082)."""
    env = scrub_host_env({"OPENCODE_API_KEY": "not-a-real-key", "OPENCODE_CONFIG": "/x"})

    assert env == {"OPENCODE_API_KEY": "not-a-real-key"}


def test_launch_re_scrubs_a_caller_supplied_env(tmp_path, monkeypatch):
    """A caller cannot put the host session back through ``env=`` (#1082)."""
    rd = runstore.create({"kind": "text", "target": str(tmp_path / "out.md")},
                         store=str(tmp_path / "store"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(argv, 0, stdout="4242\n", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)

    runstore.launch(rd, env={"MCP_SERVERS": '{"filesystem": {}}',
                             "XDG_CONFIG_HOME": "/home/someone/.config",
                             "RUN_TAG": "kept"})

    env = seen["env"]
    assert "MCP_SERVERS" not in env and "XDG_CONFIG_HOME" not in env
    assert env["RUN_TAG"] == "kept"
    assert env["PYTHONPATH"]
