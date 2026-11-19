"""A run-level call / dollar budget stops the run **at the call** (#1166).

The knobs a run already had are round-barrier budgets: ``max_calls`` is checked
between rounds, so a four-worker round on ``max_calls=1`` still makes four
calls. ``budget_usd`` is a warning plus a between-round ``stop_when``. Neither
is a cap a host can hand to a worker run and trust for one agent session.

These tests drive the run store end to end, offline: the spec builds its model
from a counting factory in this module, so every model call is one entry in
``CALLS`` and "the second call did not happen" is an assertion, not a hope.
"""

from __future__ import annotations

import pytest

from agentdescent import runstore
from agentdescent.cli import _status_line
from agentdescent.evolvespec import EvolveSpec, SpecError, compose

#: One entry per model call the spec's agent actually makes.
CALLS = []


def counting_agent(*, usage=None, tag="agent"):
    """A spec-nameable model factory that records each call."""

    def complete(prompt):
        CALLS.append(tag)
        return "ok"

    return complete


def _spec(**evolve):
    model = {"ref": "tests.test_budget_guard:counting_agent", "tag": "agent"}
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(8)]},
        agent=model, reflect=model, allow=["tests."],
        evolve={"rounds": 4, "n_workers": 4, "seed": 0, "patience": 10, **evolve})


def _run(tmp_path, *, spec=None, **limits):
    CALLS.clear()
    rd = runstore.create((spec or _spec()).to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, **limits)
    return rd, rd.status(), result


def test_max_calls_stops_before_the_next_call(tmp_path):
    rd, st, result = _run(tmp_path, max_calls=1)
    assert CALLS == ["agent"], f"a capped run made {len(CALLS)} calls"
    assert st.calls == 1
    assert st.state == "done", st
    assert st.error is None
    assert st.stop_reason == "budget", st
    assert "max_calls" in (st.stop_detail or ""), st.stop_detail
    assert result.stop_reason == "budget"


def test_max_usd_stops_before_the_call_that_would_overspend(tmp_path):
    # One call costs 0.01; the second would reach 0.02, over the 0.015 cap.
    rd, st, result = _run(tmp_path, max_usd=0.015, usd_per_call=0.01)
    assert CALLS == ["agent"], f"an over-budget run made {len(CALLS)} calls"
    assert st.state == "done", st
    assert st.error is None
    assert st.stop_reason == "budget", st
    assert "max_usd" in (st.stop_detail or ""), st.stop_detail
    assert st.usd == pytest.approx(0.01)


def test_the_status_line_names_the_limit_that_fired(tmp_path):
    rd, st, _ = _run(tmp_path, max_calls=1)
    line = _status_line(st)
    assert "budget" in line, line
    assert "max_calls" in line, line


def test_unset_limits_keep_todays_run(tmp_path):
    rd, st, result = _run(tmp_path)
    assert st.state == "done", st
    assert len(CALLS) > 1, "the uncapped run should have made more than one call"
    assert st.stop_reason != "budget", st
    assert not st.stop_detail


def test_a_negative_max_calls_is_refused_with_the_field_named():
    with pytest.raises(SpecError) as caught:
        compose(_spec(max_calls=-1))
    message = str(caught.value)
    assert "max_calls" in message and "-1" in message, message


def test_a_non_numeric_max_usd_is_refused_with_the_field_named():
    with pytest.raises(SpecError) as caught:
        compose(_spec(max_usd="cheap"))
    message = str(caught.value)
    assert "max_usd" in message and "cheap" in message, message


def test_zero_is_a_limit_not_an_absence(tmp_path):
    """``0`` means "do not spend": refused before the first call, not ignored."""
    rd, st, _ = _run(tmp_path, max_calls=0)
    assert CALLS == [], f"a zero-call budget made {len(CALLS)} calls"
    assert st.stop_reason == "budget", st
    assert "max_calls" in (st.stop_detail or ""), st.stop_detail
