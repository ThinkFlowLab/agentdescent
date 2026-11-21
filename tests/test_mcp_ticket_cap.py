"""One worker session is one Ticket: the operator ceiling is spent, not re-granted (#1082).

``AGENTDESCENT_MAX_CALLS`` caps a *run* in ``runstore.launch`` / ``execute``. A
host worker that starts a second run from the same MCP server asks again and
gets the same ceiling back, so one Ticket spends twice the number the operator
set: with ``AGENTDESCENT_MAX_CALLS=1`` two ``start`` calls each run one model
call and the Ticket bills two. The server process is the worker's session --
one Ticket in ``docs/dsh-super-agent.md`` -- so the ceiling has to hold across
the runs that server starts, and a spent Ticket refuses another start instead
of silently starting an uncapped one.
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


def _start_in(tmp_path, tools, name, **kwargs):
    sub = tmp_path / name
    sub.mkdir()
    started = tools.start(_dir_spec(str(sub)).to_dict(), **kwargs)
    assert started["ok"] is True, started
    return started


def test_second_run_is_clamped_to_what_the_ticket_has_left(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st = _wait(runstore.get(first["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st

    second = _start_in(tmp_path, tools, "t1", max_calls=5)
    # One call is already spent, so the Ticket has one left -- not five, and
    # not the untouched ceiling of two the run-level clamp would hand back.
    assert second["call_limit"]["max_calls"] == 1, second["call_limit"]
    assert second["call_limit"]["source"] == runstore.OPERATOR_MAX_CALLS_ENV
    assert second["call_limit"]["max_calls_requested"] == 5
    assert second["call_limit"]["ticket"] == {"ceiling": 2, "spent": 1, "remaining": 1}
    _wait(runstore.get(second["run_id"], store=store))


def test_a_spent_ticket_refuses_another_start(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "1")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st = _wait(runstore.get(first["run_id"], store=store))
    assert st.state == "done", st
    assert st.calls == 1, st

    sub = tmp_path / "t1"
    sub.mkdir()
    refused = tools.start(_dir_spec(str(sub)).to_dict())
    assert refused["ok"] is False, refused
    assert "AGENTDESCENT_MAX_CALLS" in refused["error"], refused["error"]
    assert "1" in refused["error"], refused["error"]
    # Nothing was created: a spent Ticket is refused before the run exists.
    assert len(runstore.list_runs(store=store)) == 1


def test_plan_reports_what_the_ticket_has_left(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st = _wait(runstore.get(first["run_id"], store=store))
    assert st.calls == 1, st

    sub = tmp_path / "t1"
    sub.mkdir()
    plan = tools.plan(_dir_spec(str(sub)).to_dict(), max_calls=9)
    assert plan["ok"] is True, plan
    # What `start` would enforce, so the host shows the number the user agrees
    # to -- 1 call left of 3, not the ceiling of 3 or the requested 9.
    assert plan["call_limit"]["max_calls"] == 2, plan["call_limit"]
    assert plan["call_limit"]["ticket"] == {"ceiling": 3, "spent": 1,
                                            "remaining": 2}


def test_a_callers_own_zero_cap_is_not_the_spent_ticket_refusal(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    tools = Tools(store)
    sub = tmp_path / "t0"
    sub.mkdir()
    plan = tools.plan(_dir_spec(str(sub)).to_dict(), max_calls=0)
    assert plan["ok"] is True, plan
    # The caller asked for zero calls with a ceiling that is untouched: that is
    # its own number, not "the Ticket is spent", so it must not carry the
    # ticket arithmetic or the refusal.
    assert plan["call_limit"]["max_calls"] == 0, plan["call_limit"]
    assert "ticket" not in plan["call_limit"], plan["call_limit"]
