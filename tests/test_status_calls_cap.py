"""A live run's ``calls=`` carries the cap it was started with (#1249).

``stop_detail`` appears only once the run has stopped, so a person watching a
live run read ``calls=137`` with no denominator while the enforced
``CallLimit.max_calls`` was known before the first call -- and the MCP
``start``/``plan`` reply had carried that number all along.

``RunStatus.calls_cap`` is that number: written by the child from the limit it
actually enforces (post-clamp, and after a Ticket's arithmetic), omitted from
``status.json`` when the run has no call cap, and rendered as
``calls=137/200``. The rows below pin both halves of that shape rule: a capped
run gains the denominator, and an uncapped one keeps yesterday's bytes.
"""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout

from agentdescent import cli, runstore
from agentdescent.evolvespec import EvolveSpec

#: One entry per model call the spec's agent actually makes.
CALLS = []
#: The run's own status as its first model call saw it -- the live view.
LIVE = []
#: The run directory the agent reads in that call (set per test).
RUN_DIR = []


def counting_agent(*, usage=None, tag="agent"):
    """A spec-nameable model factory that records each call."""

    def complete(prompt):
        CALLS.append(tag)
        if RUN_DIR and not LIVE:
            LIVE.append(RUN_DIR[0].status())
        return "ok"

    return complete


def _spec(**evolve):
    model = {"ref": "tests.test_status_calls_cap:counting_agent", "tag": "agent"}
    knobs = {"rounds": 4, "n_workers": 4, "seed": 0, "patience": 10}
    knobs.update(evolve)
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(8)]},
        agent=model, reflect=model, allow=["tests."], evolve=knobs)


def _run(tmp_path, **limits):
    CALLS.clear()
    LIVE.clear()
    RUN_DIR.clear()
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    RUN_DIR.append(rd)
    try:
        result = runstore.execute(rd, **limits)
    finally:
        RUN_DIR.clear()
    return rd, rd.status(), result


def _calls_token(line):
    """The one ``calls=...`` field of a status line."""
    tokens = [t for t in line.split() if t.startswith("calls=")]
    assert len(tokens) == 1, line
    return tokens[0]


def _cli(*args):
    """Run the CLI in-process; returns (exit code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


def test_the_operator_ceiling_is_the_denominator(tmp_path, monkeypatch):
    """Requested 50, ceiling 2: the line shows the 2 that is enforced."""
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "2")
    rd, st, _ = _run(tmp_path, max_calls=50)
    assert st.calls_cap == 2, st
    assert st.to_dict()["calls_cap"] == 2
    assert len(LIVE) == 1, "the agent never saw its own status"
    assert LIVE[0].calls_cap == 2, LIVE[0]
    assert _calls_token(cli._status_line(st)) == f"calls={st.calls}/2"


def test_a_callers_own_cap_is_the_denominator(tmp_path):
    """A cap the caller named shows too -- it is just as invisible otherwise."""
    rd, st, _ = _run(tmp_path, max_calls=1)
    assert st.calls_cap == 1, st
    assert _calls_token(cli._status_line(st)) == f"calls={st.calls}/1"


def test_a_spec_knob_cap_is_the_denominator(tmp_path):
    """With no run option, the spec's own ``evolve.max_calls`` is enforced."""
    CALLS.clear()
    LIVE.clear()
    RUN_DIR.clear()
    rd = runstore.create(_spec(max_calls=2).to_dict(),
                         store=str(tmp_path / "runs"))
    RUN_DIR.append(rd)
    try:
        runstore.execute(rd)
    finally:
        RUN_DIR.clear()
    st = rd.status()
    assert st.calls_cap == 2, st
    assert _calls_token(cli._status_line(st)) == f"calls={st.calls}/2"


def test_a_ticket_remainder_shows_the_applied_number(tmp_path, monkeypatch):
    """Ceiling 10, requested 9, a Ticket that left 3: the run enforces 3."""
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "10")
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS_REQUESTED", "9")
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_REMAINDER_ENV,
                       f"{rd.run_id}:3")
    CALLS.clear()
    LIVE.clear()
    RUN_DIR.append(rd)
    try:
        runstore.execute(rd, max_calls=3)
    finally:
        RUN_DIR.clear()
    st = rd.status()
    assert st.calls_cap == 3, st
    assert _calls_token(cli._status_line(st)) == f"calls={st.calls}/3"


def test_an_uncapped_run_keeps_todays_bytes(tmp_path):
    """No cap, no denominator, no new key -- the shape rule #1166 set."""
    rd, st, _ = _run(tmp_path)
    payload = st.to_dict()
    assert "calls_cap" not in payload, payload
    assert "/" not in _calls_token(cli._status_line(st))
    with open(os.path.join(rd.path, "status.json"), encoding="utf-8") as fh:
        on_disk = json.load(fh)
    assert "calls_cap" not in on_disk, on_disk


def test_a_dollar_only_cap_gains_no_denominator(tmp_path):
    """A dollar cap counts calls; it is not a call cap."""
    rd, st, _ = _run(tmp_path, max_usd=100.0, usd_per_call=0.01)
    assert "calls_cap" not in st.to_dict(), st
    assert "/" not in _calls_token(cli._status_line(st))


def test_an_old_status_file_still_loads_and_renders(tmp_path):
    """A ``status.json`` written before this field is not an error."""
    st = runstore.RunStatus.from_dict(
        {"run_id": "20261124-000000-abc123", "state": "running",
         "round": 3, "rounds": 10, "calls": 137})
    assert _calls_token(cli._status_line(st)) == "calls=137"
    assert "calls_cap" not in st.to_dict()


def test_json_status_exposes_the_same_number(tmp_path):
    """``--json status`` and the text line read one field, not two."""
    CALLS.clear()
    LIVE.clear()
    rd = runstore.create(_spec().to_dict(), store=str(tmp_path / "runs"))
    runstore.execute(rd, max_calls=1)
    store = str(tmp_path / "runs")
    code, out = _cli("--store", store, "--json", "status", rd.run_id)
    assert code == 0, out
    payload = json.loads(out)
    assert payload["calls_cap"] == 1, payload
    code, out = _cli("--store", store, "status", rd.run_id)
    assert code == 0, out
    assert _calls_token(out.splitlines()[0]) == "calls=1/1"
