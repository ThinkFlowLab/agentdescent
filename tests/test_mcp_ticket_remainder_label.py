"""A run clamped to the Ticket remainder has to name the ceiling (#1241).

``#1214`` made the reply and the child agree on the number. It did not make
them agree on the *reason*: when the operator's Ticket remainder is what lowered
the run, the child was launched with ``remaining < ceiling`` and
``_clamped_max_calls`` only labels a run whose applied value *equals* the
ceiling. The run then printed the same bare ``cap N`` as a caller whose own cap
happened to be that number, while the reply said ``source:
AGENTDESCENT_MAX_CALLS``.

These rows pin the label, not the enforcement: every number here is what it was
before, so a fix that changes what runs, or the reply's payload, fails them.

The control row is the trap named in the issue: ceiling 5, one call spent,
caller asks 1. The remainder (4) is larger than the caller's number, so the
ceiling never bound this run and it must stay bare -- a predicate of the form
``applied < ceiling and spent > 0`` labels it wrongly.
"""

from __future__ import annotations

import re
import time

import pytest

from agentdescent import runstore
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


def _start_in(tmp_path, tools, name, **kwargs):
    sub = tmp_path / name
    sub.mkdir()
    started = tools.start(_dir_spec(str(sub)).to_dict(), **kwargs)
    assert started["ok"] is True, started
    return started


def _spend_one(tmp_path, tools, store, ceiling=2):
    """One finished run of one call, so the Ticket has ``ceiling - 1`` left."""
    started = _start_in(tmp_path, tools, "t0", max_calls=1)
    st = _wait(runstore.get(started["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st
    return st


def test_the_remainder_that_lowered_the_cap_is_named(store, tmp_path, monkeypatch):
    """Acceptance row 1: ceiling 2, one call spent, caller asks 5 -> cap 1."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    tools = Tools(store)
    _spend_one(tmp_path, tools, store)

    second = _start_in(tmp_path, tools, "t1", max_calls=5)
    # The reply is unchanged (#1214): same number, same source, same arithmetic.
    assert second["call_limit"] == {
        "max_calls": 1, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV,
        "max_calls_requested": 5,
        "ticket": {"ceiling": 2, "spent": 1, "remaining": 1},
    }, second["call_limit"]

    st = _wait(runstore.get(second["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st
    # One line, both halves: the ceiling when it bound the number, the number
    # that was enforced.
    assert st.stop_detail == ("max_calls (AGENTDESCENT_MAX_CALLS): "
                             "1 call(s) made, cap 1"), st.stop_detail


def test_a_callers_own_cap_that_the_remainder_did_not_lower_stays_bare(
        store, tmp_path, monkeypatch):
    """Acceptance row 2, the control: ceiling 5, spent 1, caller asks 1."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    tools = Tools(store)
    _spend_one(tmp_path, tools, store, ceiling=5)

    second = _start_in(tmp_path, tools, "t1", max_calls=1)
    # The remainder (4) is larger than the caller's number, so the ceiling is
    # not what bound this run -- and the reply must not claim otherwise.
    assert second["call_limit"]["max_calls"] == 1, second["call_limit"]
    assert "source" not in second["call_limit"], second["call_limit"]
    assert second["call_limit"]["ticket"] == {
        "ceiling": 5, "spent": 1, "remaining": 4}, second["call_limit"]

    st = _wait(runstore.get(second["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st
    assert st.stop_detail == "max_calls: 1 call(s) made, cap 1", st.stop_detail
    assert runstore.OPERATOR_MAX_CALLS_ENV not in st.stop_detail, st.stop_detail


def test_a_caller_that_names_no_cap_is_still_labelled_by_the_remainder(
        store, tmp_path, monkeypatch):
    """Acceptance row 3: the caller named none, so the remainder bound it."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    tools = Tools(store)
    _spend_one(tmp_path, tools, store)

    second = _start_in(tmp_path, tools, "t1")
    assert second["call_limit"] == {
        "max_calls": 1, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV,
        "ticket": {"ceiling": 2, "spent": 1, "remaining": 1},
    }, second["call_limit"]

    st = _wait(runstore.get(second["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st
    assert st.stop_detail == ("max_calls (AGENTDESCENT_MAX_CALLS): "
                             "1 call(s) made, cap 1"), st.stop_detail


def test_the_label_does_not_change_what_the_ticket_spends(
        store, tmp_path, monkeypatch):
    """Acceptance row 4: the enforced numbers do not move with the label."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st0 = _wait(runstore.get(first["run_id"], store=store))
    assert st0.calls == 1, st0

    second = _start_in(tmp_path, tools, "t1", max_calls=9)
    assert second["call_limit"]["max_calls"] == 2, second["call_limit"]
    st1 = _wait(runstore.get(second["run_id"], store=store))
    # Two left, and it stops at them: the label is not a new grant.
    assert st1.calls == 2, st1
    assert st0.calls + st1.calls == 3, (st0.calls, st1.calls)
    m = re.search(r"cap (\d+)\s*$", st1.stop_detail or "")
    assert m and int(m.group(1)) == 2, st1.stop_detail


def test_an_inherited_remainder_cannot_label_a_caller_capped_run(
        store, tmp_path, monkeypatch):
    """The marker is inherited, not scoped: ceiling 5, stale remainder 4, caller asks 4.

    The interesting coincidence: the applied number equals both the caller's
    request and the stale marker. It is not a clamp -- the ceiling (5) did not
    lower 4 -- so the run must stay bare, and the parent must not pass the
    inherited value on.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "4")
    tools = Tools(store)

    started = _start_in(tmp_path, tools, "t0", max_calls=4)
    assert started["call_limit"]["max_calls"] == 4, started["call_limit"]
    assert "source" not in started["call_limit"], started["call_limit"]

    st = _wait(runstore.get(started["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 4, st
    assert st.stop_detail == "max_calls: 4 call(s) made, cap 4", st.stop_detail


def test_a_stale_remainder_cannot_label_a_foreground_run(tmp_path, monkeypatch):
    """The same coincidence without a detach boundary: ``execute`` in-process."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "4")
    sub = tmp_path / "fg"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, max_calls=4)
    st = rd.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 4, st
    assert st.stop_detail == "max_calls: 4 call(s) made, cap 4", st.stop_detail


def test_launch_drops_an_inherited_remainder_from_the_child_environment(
        tmp_path, monkeypatch):
    """The detach boundary itself: only this call's ``env`` may carry the marker."""
    import subprocess

    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "4")
    sub = tmp_path / "det"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, stdout="4242", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd, max_calls=4)
    assert seen["env"].get(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV) in (None, ""), \
        seen["env"].get(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV)
