"""A detached run does not inherit the host session's identity or MCP config (#1082).

The worker's own gates run under an allowlist (:func:`runners._child_env`), but
the run `launch` detaches is our process, so it needs the API keys and PATH the
allowlist would drop. The cure is a denylist of the host-session variables:
`DSH_*`, `CLAUDE*`, `CODEX*` and `MCP_*` stay with the host, everything else --
including the credentials the run needs -- is passed through.
"""

from __future__ import annotations

import os
import subprocess

from agentdescent import runstore
from agentdescent.surface_common import scrub_host_env

HOST_MARKERS = {
    "DSH_SESSION_ID": "host-session",
    "DSH_WORKSPACE": "/host/workspace",
    "CLAUDE_CODE_ENTRYPOINT": "cli",
    "CLAUDECODE": "1",
    "CODEX_SANDBOX": "1",
    "MCP_SERVERS": '{"filesystem": {}}',
}


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
