"""The governed-harness surface must pass the composition pair, not skip it (#1053).

`harness_integrity` compares two snapshots, but until now no production path
passed a pair to `govern_harness_change`, so a diff that reorders the guardrails
or drops an allow rule still reached proof and promotion. These tests go through
the surface's own entry point (`governed-harness run`), not hand-built
dataclasses, and a spec that cannot carry the pair is refused rather than
silently skipping the check.
"""
import json

import pytest

from agentdescent import cli

SNAPSHOT = {
    "guardrails": {"policy": 10, "tool_mediation": 20},
    "permissions": {"plugin:demo": ["tool:run"]},
    "actions": ["tool:run"],
    "decision_records": {
        "policy->tool_mediation": "record-1",
        "permission:plugin:demo": "record-2",
    },
    "active_plugins": ["plugin:demo"],
}


def _json_out(capsys):
    return json.loads(capsys.readouterr().out)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _changed(**overrides):
    snapshot = json.loads(json.dumps(SNAPSHOT))
    snapshot.update(overrides)
    return snapshot


def _governed_spec(tmp_path, capsys, integrity):
    """A demo governed spec with one caller-supplied composition pair."""
    spec_path = tmp_path / "governed.json"
    assert cli.main(["governed-harness", "init", "--out", str(spec_path),
                     "--demo", "--json"]) == 0
    _json_out(capsys)
    spec = json.loads(spec_path.read_text())
    spec["integrity"] = integrity
    return _write(tmp_path / "integrity.json", spec)


def test_a_reordered_guardrail_path_is_rejected_before_proof_and_promotion(
        tmp_path, capsys):
    path = _governed_spec(tmp_path, capsys, {
        "before": SNAPSHOT,
        "after": _changed(guardrails={"policy": 20, "tool_mediation": 10}),
    })

    assert cli.main(["governed-harness", "run", "--spec", path, "--json"]) == 1
    payload = _json_out(capsys)

    assert payload["promoted"] is False
    assert payload["report"]["decision"]["action"] == "reject"
    assert "guardrail_order:policy<tool_mediation" in payload["report"]["detail"]
    assert payload["report"]["proof"] is None
    relationships = [row["relationship"] for row
                     in payload["report"]["integrity"]["violations"]]
    assert "guardrail_order:policy<tool_mediation" in relationships


@pytest.mark.parametrize("change, relationship", [
    ({"permissions": {}}, "permission:plugin:demo"),
    ({"actions": ["tool:run", "tool:extra"]}, "action_set"),
])
def test_a_dropped_rule_or_an_undeclared_action_set_is_rejected(
        tmp_path, capsys, change, relationship):
    path = _governed_spec(tmp_path, capsys, {
        "before": SNAPSHOT,
        "after": _changed(**change),
    })

    assert cli.main(["governed-harness", "run", "--spec", path, "--json"]) == 1
    payload = _json_out(capsys)

    assert payload["report"]["decision"]["action"] == "reject"
    assert relationship in payload["report"]["detail"]


def test_an_intact_pair_promotes_and_the_plan_reports_it(tmp_path, capsys):
    path = _governed_spec(tmp_path, capsys, {
        "before": SNAPSHOT,
        "after": SNAPSHOT,
        "declared": {"actions_added": [], "actions_removed": []},
    })

    assert cli.main(["governed-harness", "plan", "--spec", path,
                     "--json"]) == 0
    assert _json_out(capsys)["integrity"] == "configured"

    assert cli.main(["governed-harness", "run", "--spec", path, "--json"]) == 0
    payload = _json_out(capsys)
    assert payload["promoted"] is True
    assert payload["report"]["integrity"]["ok"] is True


def test_a_malformed_pair_is_a_surface_error_not_a_skipped_check(tmp_path, capsys):
    path = _governed_spec(tmp_path, capsys, {
        "before": SNAPSHOT,
        "after": _changed(guardrails={"policy": "first"}),
    })

    assert cli.main(["governed-harness", "run", "--spec", path, "--json"]) == 2
    payload = _json_out(capsys)
    assert payload["ok"] is False
    assert "integrity" in payload["error"]
