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


def test_an_inherited_pair_cannot_label_a_foreground_run(tmp_path, monkeypatch):
    """A foreground run cannot inherit a *consistent* pair and call it a clamp.

    The pair here is exactly what a remainder-clamped parent would have in its
    own environment (ceiling 5, one call spent, caller asked 5): both halves
    agree, so no numeric test can tell it from a real handoff. ``execute`` has
    no ``env`` parameter, so an in-process run's clamp cannot have come from a
    parent's ``launch`` -- the pair is stale and the run must stay bare.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "1")
    sub = tmp_path / "fg1"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, max_calls=1)
    st = rd.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 1, st
    assert st.stop_detail == "max_calls: 1 call(s) made, cap 1", st.stop_detail


def test_an_inherited_pair_cannot_label_a_foreground_run_at_two(
        tmp_path, monkeypatch):
    """The same shape at other numbers: asked 9, remainder 2, applied 2 (#1241)."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "9")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "2")
    sub = tmp_path / "fg2"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, max_calls=2)
    st = rd.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 2, st
    assert st.stop_detail == "max_calls: 2 call(s) made, cap 2", st.stop_detail


def test_a_pair_that_names_the_ceiling_cannot_label_at_the_ceiling(
        tmp_path, monkeypatch):
    """Control: asked 5, remainder 5, applied 5 -- the caller's own number.

    The pair is consistent with a clamp *at* the ceiling, but the caller asked
    for exactly 5, so the ceiling never lowered anything: bare, before and after.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "5")
    sub = tmp_path / "fg3"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, max_calls=5)
    st = rd.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 5, st
    assert st.stop_detail == "max_calls: 5 call(s) made, cap 5", st.stop_detail


def test_a_launch_scopes_the_remainder_to_the_run_it_starts(
        tmp_path, monkeypatch):
    """The handoff names the run it was applied to, so inheriting it proves nothing.

    Only this launch knows ``rd.run_id``; the MCP server keeps handing over the
    bare number, and the scope is added exactly where the ``--max-calls`` value
    is turned into that child's argv.
    """
    import subprocess

    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.delenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, raising=False)
    sub = tmp_path / "det2"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, stdout="4243", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd, max_calls=2,
                    env={runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV: "2"})
    assert seen["env"][runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV] == \
        f"{rd.run_id}:2", seen["env"]
    # A launch that was not handed a remainder carries nothing, scoped or not.
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "9")
    sub2 = tmp_path / "det3"
    sub2.mkdir()
    other = runstore.create(_dir_spec(str(sub2)).to_dict(),
                            store=str(tmp_path / "runs"))
    runstore.launch(other, max_calls=2)
    assert seen["env"].get(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV) is None, seen["env"]


def test_a_descendant_cannot_inherit_its_ancestors_handoff(tmp_path, monkeypatch):
    """A run started inside a clamped run is a different run, with its own id.

    The env is exactly what ``launch`` leaves in run A's process, and the
    foreground run here is run B: the marker names A, so it is not evidence
    about B, however consistent the pair looks.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    sub = tmp_path / "a"
    sub.mkdir()
    run_a = runstore.create(_dir_spec(str(sub)).to_dict(),
                            store=str(tmp_path / "runs"))
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV,
                       f"{run_a.run_id}:1")
    assert runstore._remainder_calls(run_a.run_id) == (1, True)

    sub_b = tmp_path / "b"
    sub_b.mkdir()
    run_b = runstore.create(_dir_spec(str(sub_b)).to_dict(),
                            store=str(tmp_path / "runs"))
    result = runstore.execute(run_b, max_calls=1)
    st = run_b.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 1, st
    assert st.stop_detail == "max_calls: 1 call(s) made, cap 1", st.stop_detail


def test_an_inherited_marker_cannot_label_through_a_boolean_handoff(
        tmp_path, monkeypatch):
    """Whatever extra marker an ancestor's environment carries, it labels nothing.

    ``AGENTDESCENT_MAX_CALLS_FROM_LAUNCH`` is the boolean an earlier round of
    this fix used, and the inherited value is the unscoped number that round
    wrote beside it: an inherited copy must not label a run it was not applied
    to, so this row stays bare with both present.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV, "1")
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS_FROM_LAUNCH", "1")
    sub = tmp_path / "fg4"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, max_calls=1)
    st = rd.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 1, st
    assert st.stop_detail == "max_calls: 1 call(s) made, cap 1", st.stop_detail
