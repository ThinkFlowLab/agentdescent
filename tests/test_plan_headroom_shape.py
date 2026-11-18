"""`plan` says whether a paid run can learn anything, before it is paid for (#1113).

Two avoidable ways a user spends money and sees no effect:

* the seed artifact already scores 0.95+, so every round is ``below-threshold``
  and the user only learns that after paying;
* the artifact holds **one key** (``SingleSlot``, a single prompt, a one-file
  tree), so every pair of worker proposals contradicts and the fusion
  tournament never builds a fused candidate -- ``docs/results.md`` records
  ``contested == 0`` for exactly that shape, but ``plan`` did not say so.

The headroom sample is a real model call per task, against a local endpoint:
the flag is opt-in, the call count is quoted before the first call, and a
saturated seed refuses to quote the run unless ``--force`` is passed.
"""
from __future__ import annotations

import io
import os
import json
import threading
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentdescent import cli
from agentdescent.evolution import Task
from agentdescent.pilot import PilotConfig, PilotPolicy, pilot
from agentdescent.strategies import AppendRules, SingleSlot

OK = {"choices": [{"message": {"content": "ok"}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class _Handler(BaseHTTPRequestHandler):
    hits = 0
    lock = threading.Lock()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with type(self).lock:
            type(self).hits += 1
        payload = json.dumps(OK).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # noqa: D401
        pass


@pytest.fixture
def endpoint(monkeypatch):
    _Handler.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("FAKE_KEY", "sk-not-real")
    monkeypatch.setenv("FAKE_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}")
    yield
    server.shutdown()
    server.server_close()


def _model():
    return {"ref": "openai_compatible", "model": "m", "api_key_env": "FAKE_KEY",
            "base_url_env": "FAKE_BASE_URL", "retries": 0}


def _spec(tmp_path, *, gold="zzz", n=8, name="spec.json"):
    spec = {
        "version": 1,
        "kind": "text",
        "target": "You are a helpful assistant.",
        "data": {"inline": [{"prompt": f"q{i}", "gold": gold} for i in range(n)]},
        "score": "contains",
        "agent": _model(),
        "reflect": _model(),
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    }
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


def _run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


# -- the headroom sample -----------------------------------------------------


def test_plain_plan_still_samples_nothing(tmp_path, endpoint):
    """The dry run stays model-free: no flag, no call, no sample line."""
    code, out, err = _run(["plan", _spec(tmp_path)])

    assert code == 0, (out, err)
    assert _Handler.hits == 0, "plain plan must stay free"
    assert "baseline" not in (out + err).lower()


def test_the_sample_costs_one_call_per_task_and_quotes_it_first(tmp_path, endpoint):
    """`--baseline-sample N` is opt-in and priced before the first call."""
    code, out, err = _run(["plan", _spec(tmp_path), "--baseline-sample", "4",
                           "--usd-per-call", "0.01"])

    # Its own cost is named before anything is scored.
    assert "baseline sample:" in err
    assert "4 agent call(s)" in err
    assert "$0.04" in err
    assert _Handler.hits == 4, "exactly one call per sampled task"

    # And it does not change the shape of the run's own quote.
    assert code == 0, (out, err)
    assert "up to 11 agent calls" in out
    assert "baseline: the seed scores 0.000 on 4 task(s)" in out
    assert "headroom" in out


def test_a_saturated_seed_refuses_the_paid_quote(tmp_path, endpoint):
    """Baseline 1.0: say "no headroom" and do not quote the run."""
    code, out, err = _run(["plan", _spec(tmp_path, gold="ok"),
                           "--baseline-sample", "4"])

    assert code == 1, (out, err)
    assert "no headroom" in err
    assert "baseline: the seed scores 1.000 on 4 task(s)" in out
    assert "1.000" in err and "saturation 0.900" in err
    # The paid quote -- the call count and the next step -- is withheld.
    assert "up to " not in out and "agent calls" not in out
    assert "next: agentdescent evolve" not in out
    assert "refused: no headroom" in out
    assert _Handler.hits == 4


def test_force_quotes_the_run_anyway(tmp_path, endpoint):
    """`--force` is the only way to see the estimate on a saturated seed."""
    code, out, err = _run(["plan", _spec(tmp_path, gold="ok"),
                           "--baseline-sample", "4", "--force"])

    assert code == 0, (out, err)
    assert "no headroom" in err and "--force" in err
    assert "up to 11 agent calls" in out
    assert "next: agentdescent evolve" in out
    assert _Handler.hits == 4


def test_a_forced_json_plan_still_says_not_ready(tmp_path, endpoint):
    """`--force` buys the quote, not a verdict change.

    `ready` is what a host follows, so it stays false on a saturated seed even
    when the estimate was forced out: auto-starting that run is exactly what
    the flag exists to question.
    """
    code, out, err = _run(["plan", _spec(tmp_path, gold="ok"), "--json",
                           "--baseline-sample", "4", "--force"])

    payload = json.loads(out)
    assert code == 0
    assert payload["estimate"]["agent_calls_upper_bound"] == 11
    assert payload["baseline"]["headroom"] is False
    assert payload["ready"] is False
    assert any("because --force was passed" in w for w in payload["warnings"])
    assert _Handler.hits == 4


def test_a_saturated_sample_withholds_the_estimate_from_json_too(tmp_path, endpoint):
    code, out, err = _run(["plan", _spec(tmp_path, gold="ok"), "--json",
                           "--baseline-sample", "4"])

    payload = json.loads(out)
    assert code == 1
    assert payload["ok"] is True
    assert payload["baseline"] == {"sample": 4, "score": 1.0,
                                   "saturation": 0.9, "headroom": False}
    assert payload["ready"] is False
    assert _Handler.hits == 4


def test_a_baseline_sample_below_one_is_an_input_error(tmp_path, endpoint):
    code, out, err = _run(["plan", _spec(tmp_path), "--baseline-sample", "0"])

    assert code == 2
    assert "--baseline-sample must be >= 1" in err
    assert _Handler.hits == 0


def test_an_out_of_range_saturation_is_an_input_error(tmp_path, endpoint):
    code, out, err = _run(["plan", _spec(tmp_path), "--baseline-sample", "4",
                           "--saturation", "1.5"])

    assert code == 2
    assert "--saturation must be in (0, 1]" in err
    assert _Handler.hits == 0, "the input error must be caught before any call"


def test_a_saturation_without_a_sample_changes_nothing(tmp_path, endpoint):
    """`--saturation` is only read by the sample; a plain plan stays free."""
    code, out, err = _run(["plan", _spec(tmp_path), "--saturation", "0"])

    assert code == 0, (out, err)
    assert _Handler.hits == 0
    assert "baseline" not in (out + err).lower()


# -- a failed sample keeps the plan envelope (#1155) -------------------------


#: Volcengine Ark Coding, an expired plan, on HTTP 400 as measured in #1006.
ARK_SUBSCRIPTION = {
    "error": {
        "code": "InvalidSubscription",
        "message": ("Your account does not have a valid CodingPlan subscription, "
                    "or your subscription has expired."),
    }
}


class _FailHandler(BaseHTTPRequestHandler):
    body: bytes = b"{}"
    hits = 0
    lock = threading.Lock()

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        with type(self).lock:
            type(self).hits += 1
        self.send_response(400)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):  # noqa: D401
        pass


@pytest.fixture
def failing_endpoint(monkeypatch):
    _FailHandler.hits = 0
    _FailHandler.body = json.dumps(ARK_SUBSCRIPTION).encode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FailHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("FAKE_KEY", "sk-not-real")
    monkeypatch.setenv("FAKE_BASE_URL",
                       f"http://127.0.0.1:{server.server_address[1]}")
    yield
    server.shutdown()
    server.server_close()


def _store_is_empty(store: str) -> bool:
    return not os.path.exists(store) or not os.listdir(store)


def test_a_failed_baseline_sample_keeps_the_plan_and_names_the_next_step(
        tmp_path, failing_endpoint):
    """A provider failure is a config answer, like a refused probe (#1155)."""
    store = str(tmp_path / "runs")
    spec = _spec(tmp_path)
    code, out, err = _run(["--store", store, "plan", spec,
                           "--baseline-sample", "3"])

    assert code == 1, (code, out, err)
    assert "plan:" in out
    assert "baseline: scoring failed: SubscriptionInactive:" in out
    assert ("next: renew the subscription at the provider, or point "
            "api_key_env / model at another plan") in out
    assert f"then: agentdescent plan {spec} --baseline-sample 3" in out
    assert "next: agentdescent evolve" not in out
    assert "baseline sample: scoring the seed on up to 3 task(s)" in err
    assert _store_is_empty(store)


def test_a_failed_baseline_sample_json_is_a_complete_object(
        tmp_path, failing_endpoint):
    store = str(tmp_path / "runs")
    spec = _spec(tmp_path)
    code, out, err = _run(["--store", store, "plan", spec,
                           "--baseline-sample", "3", "--json"])

    payload = json.loads(out)
    assert code == 1, (code, out, err)
    assert payload["ok"] is True, "the plan itself is fine; only scoring failed"
    assert payload["ready"] is False
    assert payload["baseline"]["ok"] is False
    assert "SubscriptionInactive" in payload["baseline"]["error"]
    assert payload["next"] == (
        "renew the subscription at the provider, or point api_key_env / "
        "model at another plan")
    assert "evolve" not in payload["next"]
    assert _store_is_empty(store)


# -- the artifact-shape note -------------------------------------------------


def _tree_spec(tmp_path, files, *, name="skill-spec.json"):
    tree = tmp_path / name.replace(".json", "")
    tree.mkdir()
    for rel, text in files.items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    cli_ref = {"ref": "claude_code", "isolate": False}
    spec = {
        "version": 1,
        "kind": "skill_dir",
        "target": str(tree),
        "data": {"inline": [{"prompt": f"q{i}", "gold": "q"} for i in range(8)]},
        "score": "contains",
        "agent": dict(cli_ref),
        "reflect": dict(cli_ref),
        "prompt_template": "{prompt}",
        "evolve": {"rounds": 1, "n_workers": 4, "seed": 0},
    }
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    return str(path)


@pytest.fixture
def fake_claude(monkeypatch):
    real = cli.doctor_report

    def fake_doctor():
        report = real()
        clis = dict(report["agent_clis"])
        clis["claude"] = clis.get("claude") or "/fake/claude"
        return {**report, "agent_clis": clis}

    monkeypatch.setattr(cli, "doctor_report", fake_doctor)


def test_a_one_key_artifact_warns_that_merging_cannot_fuse(tmp_path, fake_claude):
    """A one-file tree is one key: proposals contradict, fusion never runs."""
    spec = _tree_spec(tmp_path, {"rules.md": "MODE: forward\n"})

    code, out, err = _run(["plan", spec])

    assert code == 0, (out, err)
    assert "one-key artifact (FileTree)" in err
    assert "best-of-N" in err
    assert "several keys" in err


def test_a_multi_key_artifact_says_nothing_about_merging(tmp_path, fake_claude):
    spec = _tree_spec(tmp_path, {"rules.md": "MODE: forward\n",
                                 "extra.md": "MODE: back\n"})

    code, out, err = _run(["plan", spec])

    assert code == 0, (out, err)
    assert "one-key artifact" not in err
    assert "best-of-N" not in err


# -- the same note on the pilot card ----------------------------------------


def _pilot_policy(strategy):
    train = [Task(id=f"train-{i}", prompt="q", meta={"rule": "R0"})
             for i in range(30)]
    test = [Task(id=f"test-{i}", prompt="q",
                 meta={"rule": "R0", "split": "test"}) for i in range(12)]

    def run(rendered, task):
        return "good" if "R0" in rendered else "bad"

    def reward(task, output):
        return 1.0 if output == "good" else 0.0

    def propose(rendered, task, output, reward):
        return None if "R0" in rendered else "R0"

    return PilotPolicy(tasks=train, test_tasks=test, reward=reward, run=run,
                       propose=propose, strategy=strategy, artifact_id="skill")


def _pilot_config():
    return PilotConfig(rounds=1, n_workers=1, max_concurrency=1,
                       contaminated=False)


def test_the_pilot_card_carries_the_note_once():
    report = pilot(_pilot_policy(SingleSlot()), _pilot_config())

    assert sum("one-key artifact" in note for note in report.notes) == 1
    assert report.to_markdown().count("one-key artifact") == 1


def test_the_pilot_card_is_quiet_on_a_multi_key_artifact():
    report = pilot(_pilot_policy(AppendRules()), _pilot_config())

    assert not any("one-key artifact" in note for note in report.notes)
