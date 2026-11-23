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

import os
import re
import threading
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


def _cap_in_detail(st):
    """The `cap N` a capped run actually stopped at, read from its own status.

    The reply is not the enforcement: a run whose ``stop_detail`` names a
    different number than the reply handed out is the grant mismatch this file
    exists to pin (#1082). Only a run that stopped on the call budget has one.
    """
    assert st.stop_reason == "budget", st
    m = re.search(r"cap (\d+)\s*$", st.stop_detail or "")
    assert m, st.stop_detail
    return int(m.group(1))


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
    st2 = _wait(runstore.get(second["run_id"], store=store))
    # The reply is not the enforcement: the child has to be launched with the
    # same number, or the run-level clamp hands it the whole ceiling again and
    # this Ticket bills 3 against a ceiling of 2.
    assert st2.state == "done", st2
    assert st2.calls <= 1, st2
    assert st.calls + st2.calls <= 2, (st.calls, st2.calls)
    # The child stopped where the reply said it would: `stop_detail` names the
    # same cap the host was told, so the number a host shows is the number that
    # was enforced.
    assert _cap_in_detail(st2) == second["call_limit"]["max_calls"], st2.stop_detail


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


def test_a_second_start_with_no_cap_spends_only_the_remainder(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st1 = _wait(runstore.get(first["run_id"], store=store))
    assert st1.calls == 1, st1

    # A host that names no cap of its own is the wider hole: the run-level
    # clamp turns "no number" into the full ceiling, so the remainder has to be
    # the number that crosses the detach boundary.
    second = _start_in(tmp_path, tools, "t1")
    assert second["call_limit"]["max_calls"] == 2, second["call_limit"]
    assert second["call_limit"]["source"] == runstore.OPERATOR_MAX_CALLS_ENV
    assert "max_calls_requested" not in second["call_limit"], second["call_limit"]
    st2 = _wait(runstore.get(second["run_id"], store=store))
    # The child, not the reply: it has to stop at the 2 calls that are left. At
    # `115edc74` it runs the full ceiling of 3 and this Ticket bills 4 of 3,
    # which is the overrun this test exists to pin.
    assert st2.calls == 2, st2
    assert st2.stop_reason == "budget", st2
    assert st1.calls + st2.calls == 3, (st1.calls, st2.calls)


def test_a_started_run_reserves_its_cap_before_it_spends(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=3)
    # A run that has been launched but has not written status yet has charged
    # nothing, so two overlapping starts would both take the remainder and the
    # Ticket would spend twice the ceiling. The cap it was launched with is the
    # reservation until the run reports.
    assert tools._ticket_spent() >= 3, tools._ticket_spent()

    sub = tmp_path / "t1"
    sub.mkdir()
    second = tools.start(_dir_spec(str(sub)).to_dict())
    assert second["ok"] is False, second
    assert "AGENTDESCENT_MAX_CALLS" in second["error"], second["error"]
    st1 = _wait(runstore.get(first["run_id"], store=store))
    assert st1.calls <= 3, st1
    # Refused before a run existed: one run, not two.
    assert len(runstore.list_runs(store=store)) == 1


def test_a_finished_run_gives_back_what_it_did_not_spend(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "20")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=20)
    # The reservation is the launched cap; this spec finishes well below it.
    assert tools._ticket_spent() == 20, tools._ticket_spent()
    st1 = _wait(runstore.get(first["run_id"], store=store))
    assert st1.calls < 20, st1
    # A finished run is charged what it actually used, not what it reserved:
    # otherwise an under-spending run would burn the rest of the Ticket.
    assert tools._ticket_spent() == st1.calls, (tools._ticket_spent(), st1.calls)

    second = _start_in(tmp_path, tools, "t1")
    assert second["call_limit"]["max_calls"] == 20 - st1.calls, second["call_limit"]
    st2 = _wait(runstore.get(second["run_id"], store=store))
    assert st1.calls + st2.calls <= 20, (st1.calls, st2.calls)


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


def test_two_starts_at_once_cannot_both_take_the_remainder(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    subs = []
    for name in ("t0", "t1"):
        sub = tmp_path / name
        sub.mkdir()
        subs.append(sub)
    out = []

    def go(sub):
        out.append(tools.start(_dir_spec(str(sub)).to_dict()))

    # `start` is dispatched off the event loop (`anyio.to_thread.run_sync`), so
    # two hosts calling it in the same tick is a real interleaving, not a
    # hypothetical: without one locked gate both read `spent: 0`, both take the
    # ceiling, and the Ticket bills twice it (#1082).
    threads = [threading.Thread(target=go, args=(sub,)) for sub in subs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok = [r for r in out if r["ok"]]
    refused = [r for r in out if not r["ok"]]
    assert len(ok) == 1, out
    assert refused and "AGENTDESCENT_MAX_CALLS" in refused[0]["error"], refused
    assert sum(r["call_limit"]["max_calls"] for r in ok) == 3, out
    total = sum(_wait(runstore.get(r["run_id"], store=store)).calls for r in ok)
    # One of the two took the whole ceiling and the other was refused: at
    # `115edc74` both are admitted and the Ticket bills 6 of 3.
    assert total == 3, total


def test_a_resumed_run_is_charged_to_the_ticket(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st_a = _wait(runstore.get(first["run_id"], store=store))
    second = _start_in(tmp_path, tools, "t1", max_calls=1)
    st_b = _wait(runstore.get(second["run_id"], store=store))
    assert st_a.calls + st_b.calls == 2, (st_a.calls, st_b.calls)

    # `resume` is the second entry point to the same ceiling: relaunching a run
    # is not a new Ticket, so it is clamped to the one call that is left and
    # charged for what it spends. Left ungated it got the full ceiling and was
    # never counted -- one `resume` and this Ticket billed 4 of 3 (#1082).
    resumed = tools.resume(first["run_id"])
    # The child's cap counts the ledger it resumes (1 call already made), so the
    # number it is relaunched with is 1 + 1 -- and the reply quotes the same
    # number, not the remainder it would then stop at immediately.
    assert resumed["call_limit"]["max_calls"] == 2, resumed
    assert resumed["call_limit"]["source"] == runstore.OPERATOR_MAX_CALLS_ENV
    assert resumed["call_limit"]["ticket"] == {"ceiling": 3, "spent": 2,
                                               "remaining": 1}
    st_a2 = _wait_more(runstore.get(first["run_id"], store=store), st_a.calls)
    assert st_a2.state == "done", st_a2
    # The resumed child stops at the one call that is left. At `115edc74` it
    # relaunches with the full ceiling of 3, so this run reaches 3 and the
    # Ticket bills 4 of 3.
    assert st_a2.calls - st_a.calls == 1, (st_a.calls, st_a2.calls)
    assert st_a2.calls + st_b.calls == 3, (st_a2.calls, st_b.calls)

def test_a_ceiling_bound_run_is_stopped_at_the_cap_the_reply_quotes(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    # The caller asks for nine, the ceiling grants three. The reply says 3, so
    # the child has to stop at 3: a reply that says 3 over a child stopped
    # anywhere else is the grant mismatch this file pins, not a display bug.
    first = _start_in(tmp_path, tools, "t0", max_calls=9)
    assert first["call_limit"]["max_calls"] == 3, first["call_limit"]
    assert first["call_limit"]["source"] == runstore.OPERATOR_MAX_CALLS_ENV
    st = _wait(runstore.get(first["run_id"], store=store))
    assert st.calls == 3, st
    assert _cap_in_detail(st) == first["call_limit"]["max_calls"], st.stop_detail


def test_an_unreadable_run_refuses_instead_of_granting_the_rest(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    tools = Tools(store)
    first = _start_in(tmp_path, tools, "t0", max_calls=1)
    st = _wait(runstore.get(first["run_id"], store=store))
    assert st.calls == 1, st

    # A store that lost one run's status cannot say what this Ticket spent.
    # Reading it as 0 hands the next run the rest of a budget that may already
    # be gone, so the Ticket refuses until the store is readable again.
    os.remove(runstore.get(first["run_id"], store=store).status_path)
    sub = tmp_path / "t1"
    sub.mkdir()
    refused = tools.start(_dir_spec(str(sub)).to_dict())
    assert refused["ok"] is False, refused
    assert first["run_id"] in refused["error"], refused["error"]
    assert "cannot be accounted" in refused["error"], refused["error"]
    # Refused before the run existed: one run directory, not two.
    assert len(os.listdir(store)) == 1, os.listdir(store)

    # `plan` says the same thing, so a host that plans before starting is not
    # told a remainder the Ticket is not willing to grant.
    plan_sub = tmp_path / "t2"
    plan_sub.mkdir()
    plan = tools.plan(_dir_spec(str(plan_sub)).to_dict())
    assert plan["ok"] is False, plan
    assert first["run_id"] in plan["error"], plan["error"]
    assert "cannot be accounted" in plan["error"], plan["error"]


def _external_run(tmp_path, store, name, max_calls):
    """A run in the store that this server did not start: another process did.

    Its calls are real -- it is in a run directory -- but it is not in any
    ``Tools._ticket_runs``, which is what makes it "external" to the Ticket the
    resuming server holds (#1082).
    """
    other = Tools(store)
    started = _start_in(tmp_path, other, name, max_calls=max_calls)
    st = _wait(runstore.get(started["run_id"], store=store))
    return started["run_id"], st


def test_a_resumed_external_run_cannot_exceed_the_ceiling(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    run_id, before = _external_run(tmp_path, store, "ext", max_calls=1)
    assert before.calls == 1, before

    tools = Tools(store)
    assert tools._ticket_spent() == 0, tools._ticket_spent()
    resumed = tools.resume(run_id)
    assert resumed.get("ok") is not False, resumed
    # The remainder is the grant. The child counts the ledger it resumes (one
    # call), so a cap of 3 lets it spend 2 more and stop the Ticket at 3. Today
    # the reply says 4 -- the remainder plus a ledger that is not in `spent` --
    # while `launch` clamps the child back to the ceiling: the same grant
    # mismatch this PR removes for `start`, re-entered through `resume`.
    assert resumed["call_limit"]["max_calls"] == 3, resumed["call_limit"]
    after = _wait_more(runstore.get(run_id, store=store), before.calls)
    assert after.state == "done", after
    assert _cap_in_detail(after) == resumed["call_limit"]["max_calls"], after.stop_detail
    assert after.calls - before.calls <= 2, (before.calls, after.calls)
    assert tools._ticket_spent() <= 3, tools._ticket_spent()


def test_a_resumed_external_run_is_charged_inside_the_ceiling(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    run_id, before = _external_run(tmp_path, store, "ext", max_calls=1)
    assert before.calls == 1, before

    tools = Tools(store)
    own = _start_in(tmp_path, tools, "own", max_calls=1)
    own_st = _wait(runstore.get(own["run_id"], store=store))
    assert own_st.calls == 1, own_st
    assert tools._ticket_spent() == 1, tools._ticket_spent()

    resumed = tools.resume(run_id)
    # One call of the ceiling is this server's own, so two are left. The
    # external ledger is not in `spent`: its grant is the 2 that remain, inside
    # which its earlier call is counted, so the child spends 1 more and the
    # Ticket totals 3. Today the ledger is added to the remainder the reply
    # shows (3) and the child spends 2 more: the Ticket bills 4 of 3.
    assert resumed["call_limit"]["max_calls"] == 2, resumed["call_limit"]
    after = _wait_more(runstore.get(run_id, store=store), before.calls)
    assert after.state == "done", after
    assert _cap_in_detail(after) == resumed["call_limit"]["max_calls"], after.stop_detail
    assert after.calls - before.calls == 1, (before.calls, after.calls)
    assert tools._ticket_spent() <= 3, tools._ticket_spent()


def test_a_resumed_external_run_with_no_room_is_refused(store, tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "3")
    run_id, before = _external_run(tmp_path, store, "ext", max_calls=3)
    assert before.calls == 3, before

    tools = Tools(store)
    # Its ledger already fills the ceiling the Ticket has left, and it is not
    # charged to the Ticket, so there is no remainder to grant: relaunching it
    # would hand out the ceiling a second time. Refuse, naming the run.
    refused = tools.resume(run_id)
    assert refused.get("ok") is False, refused
    assert run_id in refused["error"], refused["error"]
    assert "already carries 3 call(s)" in refused["error"], refused["error"]
    assert "pid" not in refused, refused
    after = runstore.get(run_id, store=store).status()
    assert (after.state, after.calls) == ("done", 3), after
