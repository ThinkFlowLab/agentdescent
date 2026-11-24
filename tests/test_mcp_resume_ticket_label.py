"""A registered resume has to name the Ticket ceiling in ``stop_detail`` (#1247).

``#1214`` made the reply and the child agree on the *number* for ``start``, and
``#1241`` labelled the child when the Ticket's **remainder** was the grant. A
registered ``resume`` picks a third number -- ``prior + remaining`` -- so
neither rule can see the clamp: the applied value is below the ceiling and it is
not the remainder, so no marker reached the child and the run printed a bare
``cap N`` while the reply it had just been given said
``source: AGENTDESCENT_MAX_CALLS``.

These rows pin the label only. The applied number, the ledger counted, the
Ticket's spend and the reply payload stay what they were; a fix that moves any
of them fails here, and the controls keep a launch that nothing clamped bare.
"""

from __future__ import annotations

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


def _wait_more(rd, before_calls, timeout=120):
    """Wait for a resumed run to stop again, past the calls it already had."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = rd.status()
        if st.state in ("done", "failed", "cancelled") and st.calls > before_calls:
            return st
        time.sleep(0.2)
    return rd.status()


def _start_in(tmp_path, tools, name, **kwargs):
    sub = tmp_path / name
    sub.mkdir()
    started = tools.start(_dir_spec(str(sub)).to_dict(), **kwargs)
    assert started["ok"] is True, started
    return started


def test_a_registered_resume_names_the_ticket_ceiling(store, tmp_path, monkeypatch):
    """Acceptance row 1: ceiling 3, two 1-call runs, `resume(A)` -> cap 2 of 3."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    before = _wait(runstore.get(first["run_id"], store=store))
    assert before.calls == 1, before
    second = _start_in(tmp_path, tools, "t1", max_calls=1)
    other = _wait(runstore.get(second["run_id"], store=store))
    assert other.calls == 1, other
    assert tools._ticket_spent() == 2, tools._ticket_spent()

    resumed = tools.resume(first["run_id"])
    assert resumed.get("ok") is not False, resumed
    # The reply is unchanged (#1214): same number, same source, same arithmetic.
    assert resumed["call_limit"] == {
        "max_calls": 2, "max_usd": None,
        "source": runstore.OPERATOR_MAX_CALLS_ENV,
        "ticket": {"ceiling": 3, "spent": 2, "remaining": 1},
    }, resumed["call_limit"]

    after = _wait_more(runstore.get(first["run_id"], store=store), before.calls)
    assert after.state == "done", after
    assert after.stop_reason == "budget", after
    # The grant does not move: the ledger it resumes plus the one call left.
    assert after.calls - before.calls == 1, (before.calls, after.calls)
    assert after.stop_detail == ("max_calls (AGENTDESCENT_MAX_CALLS): "
                                "2 call(s) made, cap 2"), after.stop_detail
    assert tools._ticket_spent() <= 3, tools._ticket_spent()


def test_a_caller_capped_resume_stays_bare(store, tmp_path, monkeypatch):
    """Acceptance row 2: the ceiling (4 left) never bound this caller's 1."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    before = _wait(runstore.get(first["run_id"], store=store))
    assert before.calls == 1, before

    # A caller that names its own cap below what the Ticket allows: nothing
    # clamped it, so the line must stay the bare one it printed before. The
    # resumed ledger already fills the caller's 1, so the run ends without a
    # second call -- which is exactly why the number is the caller's own.
    runstore.resume(first["run_id"], store=store, max_calls=1)
    after = _wait(runstore.get(first["run_id"], store=store))
    assert after.state == "done", after
    assert after.calls == 1, after
    assert after.stop_detail == "max_calls: 1 call(s) made, cap 1", after.stop_detail


def test_a_callers_own_cap_writes_no_ticket_marker(store, tmp_path):
    """The carrier itself: only a limit the Ticket set may leave the marker."""
    tools = Tools(store)
    # What `_call_limit_payload` returns when the caller's number is the one
    # applied: a `ticket` block but no `source`.
    caller_named = {"max_calls": 1, "max_usd": None, "max_calls_requested": 1,
                    "ticket": {"ceiling": 5, "spent": 1, "remaining": 4}}
    env = tools._ticket_env(caller_named, 1)
    assert env.get(runstore.OPERATOR_MAX_CALLS_TICKET_ENV) is None, env


def test_an_inherited_ticket_marker_cannot_label_another_run(tmp_path, monkeypatch):
    """The marker names its run, so a descendant's copy is not evidence about it."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    sub = tmp_path / "a"
    sub.mkdir()
    run_a = runstore.create(_dir_spec(str(sub)).to_dict(),
                            store=str(tmp_path / "runs"))
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REQUESTED_ENV, "5")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_TICKET_ENV,
                       f"{run_a.run_id}:1")

    sub_b = tmp_path / "b"
    sub_b.mkdir()
    run_b = runstore.create(_dir_spec(str(sub_b)).to_dict(),
                            store=str(tmp_path / "runs"))
    result = runstore.execute(run_b, max_calls=1)
    st = run_b.status()
    assert result.stop_reason is None or result.stop_reason == "budget", result
    assert st.calls == 1, st
    assert st.stop_detail == "max_calls: 1 call(s) made, cap 1", st.stop_detail


def test_launch_scopes_the_ticket_marker_to_the_run_it_starts(tmp_path, monkeypatch):
    """The detach boundary: only this call's ``env`` may carry the marker."""
    import subprocess

    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.delenv(runstore.OPERATOR_MAX_CALLS_TICKET_ENV, raising=False)
    sub = tmp_path / "det"
    sub.mkdir()
    rd = runstore.create(_dir_spec(str(sub)).to_dict(), store=str(tmp_path / "runs"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, stdout="4244", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd, max_calls=2,
                    env={runstore.OPERATOR_MAX_CALLS_TICKET_ENV: "2"})
    assert seen["env"][runstore.OPERATOR_MAX_CALLS_TICKET_ENV] == \
        f"{rd.run_id}:2", seen["env"]

    # A launch that was not handed a marker carries nothing, inherited or not.
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_TICKET_ENV, "9")
    sub2 = tmp_path / "det2"
    sub2.mkdir()
    other = runstore.create(_dir_spec(str(sub2)).to_dict(),
                            store=str(tmp_path / "runs"))
    runstore.launch(other, max_calls=2)
    assert seen["env"].get(runstore.OPERATOR_MAX_CALLS_TICKET_ENV) is None, seen["env"]
