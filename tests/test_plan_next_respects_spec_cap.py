"""``plan``'s ``next:`` must not raise a cap the spec already declares (#1219).

``runstore.py:1021-1024`` states the rule the advice broke: an explicit run
option "wins over a spec's own knobs". ``next:`` printed ``--max-calls`` at the
structural bound, so a spec declaring ``evolve.max_calls: 5`` was advised to run
with 11 -- following the advice silently raised the user's own cap. The same
declaration also has to agree on both surfaces: ``next:`` and ``--json.next``
are one string, so a host reading the payload sees the same command a person
does.

The bound itself is the engine's structural number, not the CLI's advice, and
``--json.estimate.agent_calls_upper_bound`` stays exactly what it was (#1219
acceptance 4).
"""

import io
import json
from contextlib import redirect_stdout

from agentdescent import cli


def _spec(tmp_path, n=8, **evolve):
    rows = [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(n)]
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
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _plan(tmp_path, *extra, **evolve):
    """Run ``plan`` in both forms; return (path, text next, json doc)."""
    path = _spec(tmp_path, **evolve)
    code, out = _run(["plan", path, *extra])
    assert code == 0, out
    text_next = next(
        line[len("next: "):] for line in out.splitlines() if line.startswith("next: "))
    code, out = _run(["plan", path, *extra, "--json"])
    assert code == 0, out
    return path, text_next, json.loads(out)


def test_a_declared_max_calls_is_not_raised_by_the_advice(tmp_path):
    path, text_next, doc = _plan(tmp_path, max_calls=5)
    # The bound is untouched: it is the engine's number, not the advice's.
    assert doc["estimate"]["agent_calls_upper_bound"] == 11
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 5"), text_next
    assert doc["next"] == text_next


def test_a_declared_cap_above_the_bound_uses_the_bound(tmp_path):
    # min(bound, declared): a larger declaration does tighten nothing, and the
    # advice must not print a number the plan itself does not support.
    path, text_next, doc = _plan(tmp_path, max_calls=50)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 11"), text_next
    assert doc["next"] == text_next


def test_a_declared_dollar_cap_suppresses_the_call_cap(tmp_path):
    # `max_usd` + `usd_per_call` is a cap the advice cannot express as calls:
    # print no `--max-calls` at all, so the spec's dollar cap governs.
    path, text_next, doc = _plan(tmp_path, max_usd=0.05, usd_per_call=0.01)
    assert "--max-calls" not in text_next, text_next
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path}"), text_next
    assert doc["next"] == text_next


def test_without_a_declared_cap_the_bound_is_still_named(tmp_path):
    # The #1201 / #1217 contract, unchanged.
    path, text_next, doc = _plan(tmp_path)
    assert text_next == (
        f"agentdescent plan {path} --probe, then "
        f"agentdescent evolve {path} --max-calls 11"), text_next
    assert doc["next"] == text_next


def test_a_plan_that_already_probed_keeps_the_declared_cap(tmp_path):
    path, text_next, doc = _plan(tmp_path, "--probe", max_calls=5)
    assert text_next == f"agentdescent evolve {path} --max-calls 5", text_next
    assert doc["next"] == text_next
