"""The MCP `plan` tool can run the #1048 preflight (#1094).

The CLI has had `plan --probe` since #1048, but a host that drives the MCP
server (Claude Code, Codex, dsh, OpenCode, Grok Bot) could only call `plan`,
which runs nothing. So the first real answer about an expired subscription or a
wrong model name arrived after `start`, as a failed run store entry -- exactly
what the flag exists to prevent on the CLI side. The same is true of the host
skill: it teaches `plan` -> user yes -> `start`, and never mentions the probe.

These rows pin the tool contract (`probe` is opt-in, reports the same payload
`probe_payload` returns, and a refusal makes `ok` false with a repair `next`),
the one probe verdict both surfaces publish (`ready`, #1175) and the host
template (every generated SKILL.md teaches the probe).
"""
from __future__ import annotations

import io
import json
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentdescent import cli
from agentdescent.integrations import HOSTS, host_status, install
from agentdescent.mcp import Tools

OK = {"choices": [{"message": {"content": "ok"}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

#: Volcengine Ark Coding, an expired plan, on HTTP 400 as measured in #1006.
ARK_SUBSCRIPTION = {
    "error": {
        "code": "InvalidSubscription",
        "message": ("Your account does not have a valid CodingPlan subscription, "
                    "or your subscription has expired."),
    }
}

#: What `Tools().plan(spec)` returned before the probe existed (base
#: f8efc73), for the spec below: a fresh key set or a dropped key is a shape
#: change a host would see, so the default path is pinned key by key.
BASE_PLAN_KEYS = {
    "artifact_id", "estimate", "evolve_kwargs", "kind", "notes", "ok", "spec",
    "tasks", "warnings",
}


class _Handler(BaseHTTPRequestHandler):
    url: str = ""
    body: bytes = b"{}"
    code: int = 400
    hits = 0
    lock = threading.Lock()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with type(self).lock:
            type(self).hits += 1
        payload = (json.dumps(OK).encode() if type(self).code == 200
                   else type(self).body)
        self.send_response(type(self).code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: D401
        pass


@pytest.fixture
def endpoint(monkeypatch):
    _Handler.hits = 0
    _Handler.code = 400
    _Handler.body = b"{}"
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Handler.url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("FAKE_KEY", "sk-not-real")
    monkeypatch.setenv("FAKE_BASE_URL", _Handler.url)

    def use(*, code=400, body=None):
        _Handler.code = code
        _Handler.body = json.dumps(body if body is not None else {}).encode()
        _Handler.hits = 0

    yield use
    server.shutdown()
    server.server_close()


def _spec():
    model = {"ref": "openai_compatible", "model": "m", "api_key_env": "FAKE_KEY",
             "base_url_env": "FAKE_BASE_URL", "retries": 1}
    return {
        "version": 1,
        "kind": "text",
        "target": "You are a helpful assistant.",
        "data": {"inline": [{"prompt": f"q{i}", "gold": "zzz"} for i in range(8)]},
        "agent": dict(model),
        "reflect": dict(model),
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    }


def test_a_refused_probe_makes_the_mcp_plan_refuse_the_start(tmp_path, endpoint):
    endpoint(code=400, body=ARK_SUBSCRIPTION)
    out = Tools(str(tmp_path / "runs")).plan(_spec(), probe=True)
    assert out["ok"] is False, out
    assert out["probe"]["ok"] is False
    failed = [row for row in out["probe"]["rows"] if row["state"] == "failed"]
    assert failed, out["probe"]["rows"]
    assert "start" not in out["next"].lower(), out["next"]
    assert _Handler.hits == 1          # one probe call, nothing else ran


def test_a_healthy_probe_keeps_the_mcp_plan_ok(tmp_path, endpoint):
    endpoint(code=200)
    out = Tools(str(tmp_path / "runs")).plan(_spec(), probe=True)
    assert out["ok"] is True, out
    assert out["probe"]["ok"] is True
    assert [row["state"] for row in out["probe"]["rows"]] == ["ok"]
    assert _Handler.hits == 1


def test_omitting_the_probe_returns_exactly_the_old_payload(tmp_path):
    out = Tools(str(tmp_path / "runs")).plan(_spec())
    assert set(out) == BASE_PLAN_KEYS, sorted(set(out) ^ BASE_PLAN_KEYS)
    assert "probe" not in out


def test_every_host_skill_teaches_the_probe(tmp_path):
    for host in HOSTS:
        install(host, home=str(tmp_path))
    skills = sorted(Path(tmp_path).rglob("SKILL.md"))
    assert len(skills) >= 5, skills
    for path in skills:
        text = path.read_text(encoding="utf-8").lower()
        assert "probe" in text, path
    # doctor reads the same host_status: every host is still wired and current.
    for host in HOSTS:
        status = host_status(host, home=str(tmp_path))
        assert status["state"] == "ok", (host, status)
        assert status["skill"] == "ok", (host, status)


def _write_spec(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    return str(path)


def _cli_plan(spec_path):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(["plan", spec_path, "--json", "--probe"])
    return code, out.getvalue(), err.getvalue()


def test_both_surfaces_publish_the_same_refusal_triple(tmp_path, endpoint):
    """#1175: a refused probe prints one contract on both surfaces.

    `(ok, ready, next)` is identical -- ``false``, ``false``, the repair
    sentence. `ok` is not "the spec parsed": a run that cannot start is not
    success on either surface, and a host that ports its check from the CLI to
    MCP (or back) reaches the same verdict from either key.
    """
    endpoint(code=400, body=ARK_SUBSCRIPTION)

    cli_code, cli_out, cli_err = _cli_plan(_write_spec(tmp_path))
    cli_payload = json.loads(cli_out)
    mcp_payload = Tools(str(tmp_path / "runs")).plan(_spec(), probe=True)

    assert cli_code == 1, (cli_code, cli_err)
    cli_triple = (cli_payload["ok"], cli_payload["ready"], cli_payload["next"])
    mcp_triple = (mcp_payload["ok"], mcp_payload["ready"], mcp_payload["next"])
    assert cli_triple == mcp_triple, (cli_triple, mcp_triple)
    assert cli_triple[0] is False and cli_triple[1] is False
    assert cli_triple[2].startswith("renew the subscription"), cli_triple[2]
    assert cli_payload["probe"]["ok"] is False
    assert mcp_payload["probe"]["ok"] is False
    assert _Handler.hits == 2                  # one probe call per surface


def test_both_surfaces_publish_ok_and_ready_true_for_a_healthy_probe(tmp_path,
                                                                     endpoint):
    endpoint(code=200)

    cli_code, cli_out, cli_err = _cli_plan(_write_spec(tmp_path))
    cli_payload = json.loads(cli_out)
    mcp_payload = Tools(str(tmp_path / "runs")).plan(_spec(), probe=True)

    assert cli_code == 0, (cli_code, cli_err)
    assert (cli_payload["ok"], cli_payload["ready"]) == (True, True)
    assert (mcp_payload["ok"], mcp_payload["ready"]) == (True, True)


def test_the_mcp_plan_without_a_probe_has_no_ready_key(tmp_path):
    out = Tools(str(tmp_path / "runs")).plan(_spec())
    assert "ready" not in out
