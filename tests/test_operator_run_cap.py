"""An operator's per-run call ceiling the caller cannot raise (#1082).

``--max-calls`` is the caller's cap. This is the operator's, read from
``AGENTDESCENT_MAX_CALLS`` and clamped into the run store's two run paths:
``launch`` (detached) and ``execute`` (foreground). The clamp is a min -- a
caller may ask for fewer calls than the ceiling, never more, and a run that
passes no ``max_calls`` at all still gets the ceiling.
"""

from __future__ import annotations

import subprocess

import pytest

from agentdescent import runstore
from agentdescent.evolvespec import EvolveSpec

#: One entry per model call the spec's agent actually makes.
CALLS = []


def counting_agent(*, usage=None, tag="agent"):
    """A spec-nameable model factory that records each call."""

    def complete(prompt):
        CALLS.append(tag)
        return "ok"

    return complete


def _spec():
    model = {"ref": "tests.test_operator_run_cap:counting_agent", "tag": "agent"}
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(8)]},
        agent=model, reflect=model, allow=["tests."],
        evolve={"rounds": 4, "n_workers": 4, "seed": 0, "patience": 10})


def _run(tmp_path, **limits):
    CALLS.clear()
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    result = runstore.execute(rd, **limits)
    return rd, rd.status(), result


def test_the_operator_ceiling_lowers_a_callers_larger_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd, st, result = _run(tmp_path, max_calls=50)
    assert len(CALLS) == 2, f"the ceiling let {len(CALLS)} calls through"
    assert st.state == "done", st
    assert st.stop_reason == "budget", st
    assert "AGENTDESCENT_MAX_CALLS" in (st.stop_detail or ""), st.stop_detail
    assert result.stop_reason == "budget"


def test_the_operator_ceiling_applies_with_no_caller_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd, st, _ = _run(tmp_path)
    assert len(CALLS) == 2, f"the ceiling let {len(CALLS)} calls through"
    assert st.stop_reason == "budget", st
    assert "AGENTDESCENT_MAX_CALLS" in (st.stop_detail or ""), st.stop_detail


def test_a_loose_operator_ceiling_never_loosens_the_callers_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "50")
    rd, st, _ = _run(tmp_path, max_calls=1)
    assert len(CALLS) == 1, f"the caller's cap let {len(CALLS)} calls through"
    assert st.stop_reason == "budget", st
    assert "max_calls" in (st.stop_detail or ""), st.stop_detail
    # The caller's own cap fired, so the operator's name has no business here.
    assert "AGENTDESCENT_MAX_CALLS" not in (st.stop_detail or ""), st.stop_detail


def test_a_detached_run_carries_the_operator_ceiling(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="4242", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd, max_calls=50)
    argv = seen["argv"]
    assert argv[argv.index("--max-calls") + 1] == "2", argv


def test_a_dollar_stop_never_names_the_call_ceiling(tmp_path, monkeypatch):
    """The two caps are independent: a USD stop must not blame the call knob.

    A run can carry both the operator's call ceiling and the caller's
    ``--max-usd``. The USD refusal happens before any call, so the call ceiling
    never bound it -- naming it in ``stop_detail`` would point the reader at a
    knob that did nothing.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd, st, _ = _run(tmp_path, max_usd=0.01, usd_per_call=0.01)
    assert st.stop_reason == "budget", st
    detail = st.stop_detail or ""
    assert "max_usd" in detail, detail
    assert "AGENTDESCENT_MAX_CALLS" not in detail, detail


def test_the_detached_child_learns_what_the_caller_asked(tmp_path, monkeypatch):
    """The child sees the clamped argv, so the label travels separately (#1082).

    ``launch`` starts the child with ``--max-calls 2`` (the ceiling), which on its
    own is indistinguishable from a caller who asked for 2. The requested number
    rides in an internal variable so the child's ``status`` can still say which
    knob bound the run; it never changes what is enforced.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(argv, 0, stdout="4242", stderr="")

    monkeypatch.setattr(runstore.subprocess, "run", fake_run)
    runstore.launch(rd, max_calls=50)
    argv = seen["argv"]
    assert argv[argv.index("--max-calls") + 1] == "2", argv
    assert seen["env"].get("AGENTDESCENT_MAX_CALLS_REQUESTED") == "50", seen["env"]


def test_the_detached_run_names_the_ceiling_the_parent_applied(tmp_path, monkeypatch):
    """The child's own view: requested 50, ceiling 2, argv capped at 2."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS_REQUESTED", "50")
    rd, st, _ = _run(tmp_path, max_calls=2)
    assert len(CALLS) == 2, f"the ceiling let {len(CALLS)} calls through"
    assert st.stop_reason == "budget", st
    assert "AGENTDESCENT_MAX_CALLS" in (st.stop_detail or ""), st.stop_detail


def test_an_equal_cap_does_not_name_the_ceiling(tmp_path, monkeypatch):
    """Caller asked for exactly the ceiling: the caller's number bound it."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS_REQUESTED", "2")
    rd, st, _ = _run(tmp_path, max_calls=2)
    assert st.stop_reason == "budget", st
    assert "AGENTDESCENT_MAX_CALLS" not in (st.stop_detail or ""), st.stop_detail



def test_a_hand_set_request_does_not_blame_a_looser_ceiling(tmp_path, monkeypatch):
    """The label follows the clamp: caller 2, ceiling 5, a stale request of 50.

    The variable only exists so a detached child can report what the caller
    asked for. A hand-set or inherited value must not make the run blame a
    ceiling that never bound it, and it must not change what is enforced: the
    caller's cap of 2 still stops the run at 2 calls.
    """
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "5")
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS_REQUESTED", "50")
    rd, st, _ = _run(tmp_path, max_calls=2)
    assert len(CALLS) == 2, f"the caller's cap let {len(CALLS)} calls through"
    assert st.stop_reason == "budget", st
    detail = st.stop_detail or ""
    assert "max_calls" in detail, detail
    assert "AGENTDESCENT_MAX_CALLS" not in detail, detail
