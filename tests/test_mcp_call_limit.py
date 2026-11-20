"""An MCP host can cap a run: `plan` / `start` take `max_calls` / `max_usd` (#1184).

The CLI and the run store already carry the run-level cap (#1166) and the
operator ceiling (#1082). This is the third surface: a host that calls `start`
from a tool can now say "at most N model calls for this run", hears the CLI's
own refusal when it asks for a dollar cap with no price, and sees the clamped
number (requested vs enforced) when ``AGENTDESCENT_MAX_CALLS`` binds.
"""

from __future__ import annotations

import subprocess
import time

import pytest

from agentdescent import runstore
from agentdescent.cli import NESTED_ENV
from agentdescent.evolvespec import SpecError, build_call_limit
from agentdescent.mcp import Tools

from tests.test_evolvespec import _dir_spec  # noqa: F401


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(tmp_path))
    return str(tmp_path / "runs")


def _wait(rd, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = rd.status()
        if st.state in ("done", "failed", "cancelled"):
            return st
        time.sleep(0.2)
    raise AssertionError(rd.status())


def test_plan_reports_the_cap_it_will_enforce(store, tmp_path):
    t = Tools(store)
    payload = t.plan(_dir_spec(str(tmp_path)).to_dict(), max_calls=3)
    assert payload["ok"] is True, payload
    assert payload["call_limit"] == {"max_calls": 3, "max_usd": None}


def test_plan_without_a_cap_is_unchanged(store, tmp_path):
    t = Tools(store)
    payload = t.plan(_dir_spec(str(tmp_path)).to_dict())
    assert payload["ok"] is True, payload
    assert "call_limit" not in payload


def test_start_caps_the_run_and_status_shows_it(store, tmp_path):
    t = Tools(store)
    started = t.start(_dir_spec(str(tmp_path)).to_dict(), max_calls=1)
    assert started["ok"] is True, started
    assert started["call_limit"] == {"max_calls": 1, "max_usd": None}
    st = _wait(runstore.get(started["run_id"], store=store))
    assert st.state == "done", st
    assert st.stop_reason == "budget", st
    assert "max_calls" in (st.stop_detail or ""), st.stop_detail
    assert st.calls == 1, st


def test_start_without_a_cap_is_unchanged(store, tmp_path):
    t = Tools(store)
    started = t.start(_dir_spec(str(tmp_path)).to_dict())
    assert started["ok"] is True, started
    assert "call_limit" not in started


def test_max_usd_alone_is_refused_with_the_cli_sentence(store, tmp_path):
    t = Tools(store)
    spec = _dir_spec(str(tmp_path)).to_dict()
    plan = t.plan(spec, max_usd=1.0)
    start = t.start(spec, max_usd=1.0)
    with pytest.raises(SpecError) as raised:
        build_call_limit(max_usd=1.0)
    for payload in (plan, start):
        assert payload["ok"] is False, payload
        # The CLI's wording, not a second sentence for this surface.
        assert payload["error"] == str(raised.value), payload["error"]
    assert t.status()["runs"] == [], "a refused cap must not leave a run behind"


def test_a_caller_cap_above_the_operator_ceiling_is_clamped_and_labelled(
        store, tmp_path, monkeypatch):
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "2")
    t = Tools(store)
    spec = _dir_spec(str(tmp_path)).to_dict()
    assert t.plan(spec, max_calls=9)["call_limit"] == {
        "max_calls": 2, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV, "max_calls_requested": 9}
    started = t.start(spec, max_calls=9)
    assert started["call_limit"] == {
        "max_calls": 2, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV, "max_calls_requested": 9}, started
    st = _wait(runstore.get(started["run_id"], store=store))
    assert st.calls == 2, f"the ceiling let {st.calls} calls through"
    assert st.stop_reason == "budget", st
    assert runstore.OPERATOR_MAX_CALLS_ENV in (st.stop_detail or ""), st.stop_detail


def test_a_cap_equal_to_the_ceiling_is_not_reported_as_bound(
        store, tmp_path, monkeypatch):
    """Same rule as `_clamped_max_calls`: requested == ceiling did not bind.

    The payload and `stop_detail` are derived in two places (`mcp.py` here,
    `runstore._clamped_max_calls` for the run), so a host that was told "the
    ceiling lowered you" about a caller who asked for exactly the ceiling would
    be reading a lie the run does not share.
    """
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "2")
    payload = Tools(store).plan(_dir_spec(str(tmp_path)).to_dict(), max_calls=2)
    assert payload["call_limit"] == {"max_calls": 2, "max_usd": None}, payload


def test_a_run_that_names_no_cap_still_gets_the_ceiling(
        store, tmp_path, monkeypatch):
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "2")
    payload = Tools(store).plan(
        _dir_spec(str(tmp_path)).to_dict(), usd_per_call=None)
    assert payload["call_limit"] == {
        "max_calls": 2, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV}, payload


def test_start_hands_the_clamped_cap_to_the_detached_child(
        store, tmp_path, monkeypatch):
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "2")
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="4242", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    started = Tools(store).start(_dir_spec(str(tmp_path)).to_dict(), max_calls=9)
    assert started["ok"] is True, started
    argv = seen["argv"]
    assert argv[argv.index("--max-calls") + 1] == "2", argv


def test_nested_start_is_unchanged(store, tmp_path, monkeypatch):
    monkeypatch.setenv(NESTED_ENV, "1")
    t = Tools(store)
    payload = t.start(_dir_spec(str(tmp_path)).to_dict(), max_calls=1)
    assert payload == {
        "ok": True, "run_id": "nested-stub", "state": "refused", "nested": True,
        "reason": "nested-run", "note": payload["note"]}, payload
    assert t.status()["runs"] == []
