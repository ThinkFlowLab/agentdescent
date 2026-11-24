"""``plan`` must not advise a call cap the operator ceiling clamps away (#1252).

``AGENTDESCENT_MAX_CALLS`` is enforced two ways: ``runstore.launch`` clamps a
foreground ``evolve --max-calls N`` to the ceiling, and the MCP ``start`` tool
clamps it per Ticket. The advice path consulted neither, so with
``AGENTDESCENT_MAX_CALLS=2`` and a 52-call estimate ``plan`` printed
``next: ... --max-calls 52`` and ``warnings: []``: the first run a user starts
from that line stops after two calls, and the reply named a cap the operator
had already refused. ``#1219`` fixed the same class for a cap the *spec*
declares; this is the ceiling's face of it.

Reporting only: ``estimate.agent_calls_upper_bound``, ``call_limit``'s numbers
and every stop reason stay exactly what they were. An uncapped plan's text and
JSON are unchanged, and a spec whose declared cap is below the ceiling keeps
its own number with no warning.

The second face is the Ticket remainder, known before a run starts: a spent
Ticket made ``Tools.plan`` answer ``ok: true`` with ``max_calls: 0`` while the
``start`` beside it refused in one sentence. Both entry points now answer with
that same sentence, byte for byte.
"""

import io
import json
import time
from contextlib import redirect_stderr, redirect_stdout

import pytest

from agentdescent import cli, runstore
from agentdescent.mcp import Tools

from tests.test_evolvespec import _dir_spec


# ---------------------------------------------------------------------------
# the CLI advice
# ---------------------------------------------------------------------------

def _spec(tmp_path, **evolve):
    """The 8-task text spec ``#1219`` uses; its structural bound is 11 calls."""
    rows = [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(8)]
    prompt = tmp_path / "prompt.md"
    prompt.write_text("Answer.\n", encoding="utf-8")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({
        "kind": "text", "target": str(prompt),
        "data": {"path": str(cases)}, "score": "contains",
        "agent": "echo", "reflect": "echo",
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0, **evolve},
    }), encoding="utf-8")
    return str(path)


def _run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def _next_line(out):
    return next(line[len("next: "):] for line in out.splitlines()
                if line.startswith("next: "))


def _plan(tmp_path, monkeypatch, *extra, ceiling=None, **evolve):
    """Run ``plan`` in both forms under ``ceiling``; return the two surfaces."""
    if ceiling is None:
        monkeypatch.delenv(runstore.OPERATOR_MAX_CALLS_ENV, raising=False)
    else:
        monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, str(ceiling))
    path = _spec(tmp_path, **evolve)
    code, out, err = _run(["plan", path, *extra])
    assert code == 0, (out, err)
    text_next = _next_line(out)
    code, jout, jerr = _run(["plan", path, *extra, "--json"])
    assert code == 0, (jout, jerr)
    return path, text_next, json.loads(jout), out, err


CEILING_WARNING = ("AGENTDESCENT_MAX_CALLS=2 caps this run at 2 calls; "
                   "the plan estimates 11")


def test_the_ceiling_lowers_the_advised_cap(tmp_path, monkeypatch):
    path, text_next, doc, out, err = _plan(tmp_path, monkeypatch, ceiling=2)
    # The advice may not name a number `evolve` will clamp away.
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 2"), text_next
    assert doc["next"] == text_next
    # Reporting only: the engine's own bound is untouched.
    assert doc["estimate"]["agent_calls_upper_bound"] == 11, doc["estimate"]
    assert CEILING_WARNING in doc["warnings"], doc["warnings"]
    # The human form prints the same sentence, as a warning on stderr.
    assert f"warning: {CEILING_WARNING}" in err, err


def test_a_declared_cap_below_the_ceiling_is_kept_and_adds_no_warning(
        tmp_path, monkeypatch):
    path, text_next, doc, out, err = _plan(
        tmp_path, monkeypatch, ceiling=20, max_calls=5)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 5"), text_next
    assert doc["next"] == text_next
    assert not [w for w in doc["warnings"] if "AGENTDESCENT_MAX_CALLS" in w], doc


def test_a_spec_declaring_ten_keeps_ten_while_the_ceiling_is_above_it(
        tmp_path, monkeypatch):
    # The acceptance row from the issue: the declared 10 is what the advice
    # names, and a ceiling above it lowers nothing.
    path, text_next, doc, out, err = _plan(
        tmp_path, monkeypatch, ceiling=20, max_calls=10)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 10"), text_next
    assert doc["next"] == text_next
    assert not [w for w in doc["warnings"] if "AGENTDESCENT_MAX_CALLS" in w], doc


def test_a_declared_cap_above_the_ceiling_uses_the_ceiling(tmp_path, monkeypatch):
    path, text_next, doc, out, err = _plan(
        tmp_path, monkeypatch, ceiling=6, max_calls=10)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 6"), text_next
    assert doc["next"] == text_next
    assert ("AGENTDESCENT_MAX_CALLS=6 caps this run at 6 calls; "
            "the plan estimates 11") in doc["warnings"], doc["warnings"]


def test_a_probed_plan_advice_is_capped_too(tmp_path, monkeypatch):
    # After `--probe` the advice is the evolve command alone; it still may not
    # name a number the ceiling clamps away.
    path, text_next, doc, out, err = _plan(tmp_path, monkeypatch, "--probe", ceiling=2)
    assert text_next == f"agentdescent evolve {path} --max-calls 2", text_next
    assert doc["next"] == text_next


def test_an_uncapped_plan_names_no_ceiling(tmp_path, monkeypatch):
    # No ceiling: the advice, the payload and the stream are what they were --
    # nothing from this report leaks into a run nobody capped.
    path, text_next, doc, out, err = _plan(tmp_path, monkeypatch)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 11"), text_next
    assert doc["next"] == text_next
    assert doc["warnings"] == [], doc["warnings"]
    assert "AGENTDESCENT_MAX_CALLS" not in json.dumps(doc)
    assert "AGENTDESCENT_MAX_CALLS" not in out + err


def test_a_malformed_ceiling_is_an_input_error(tmp_path, monkeypatch):
    # The advice now reads the ceiling, so a value `evolve` would refuse has to
    # be a config answer here too, not a traceback out of `plan`.
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "two")
    path = _spec(tmp_path)
    code, out, err = _run(["plan", path])
    assert code == 2, (code, out, err)
    assert ("error: AGENTDESCENT_MAX_CALLS must be a non-negative integer, "
            "got 'two'") in err, err
    code, jout, jerr = _run(["plan", path, "--json"])
    assert code == 2, (code, jout, jerr)
    doc = json.loads(jout)
    assert doc == {"ok": False,
                   "error": ("AGENTDESCENT_MAX_CALLS must be a non-negative "
                             "integer, got 'two'")}, doc


# ---------------------------------------------------------------------------
# the MCP Ticket remainder
# ---------------------------------------------------------------------------

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


def test_a_spent_ticket_makes_plan_refuse_in_starts_sentence(store, tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv(runstore.OPERATOR_MAX_CALLS_ENV, "1")
    tools = Tools(store)
    sub = tmp_path / "t0"
    sub.mkdir()
    started = tools.start(_dir_spec(str(sub)).to_dict(), max_calls=1)
    assert started["ok"] is True, started
    st = _wait(runstore.get(started["run_id"], store=store))
    assert st.calls == 1, st

    sub = tmp_path / "t1"
    sub.mkdir()
    spec = _dir_spec(str(sub)).to_dict()
    plan = tools.plan(spec, max_calls=5)
    # A spent Ticket has nothing to grant: the plan may not answer `ok: true`
    # with `max_calls: 0` for a run `start` refuses.
    assert plan["ok"] is False, plan
    assert "already spent by this worker's Ticket" in plan["error"], plan
    assert plan["call_limit"]["max_calls"] == 0, plan["call_limit"]
    # Byte for byte what `start` answers for the same spent Ticket.
    refused = tools.start(spec, max_calls=5)
    assert plan == refused, (plan, refused)
    # Refused before a run existed: the Ticket still holds one run.
    assert len(runstore.list_runs(store=store)) == 1
