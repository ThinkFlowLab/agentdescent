"""Pilot is the last mile: one run, one decision, one honest report (#937).

The engine already proves it can evolve an artifact. These tests pin the part a
user reads: the same disjoint test tasks are scored before and after, a task
that raised is run-health evidence rather than a zero, and a flat, contaminated
or unhealthy run cannot come back as ``promote``.
"""

import json

from agentdescent.evolution import Task
from agentdescent.pilot import (PilotConfig, PilotPolicy, pilot,
                                pilot_scores)
from agentdescent.promotion import PromotionAction
from agentdescent.strategies import AppendRules


def _policy(*, flat=False, fail_ids=(), rules=3, train_n=30, test_n=12):
    names = [f"R{i}" for i in range(rules)]
    train = [Task(id=f"train-{i}", prompt="q",
                  meta={"rule": names[i % rules]}) for i in range(train_n)]
    test = [Task(id=f"test-{i}", prompt="q",
                 meta={"rule": names[i % rules], "split": "test"})
            for i in range(test_n)]

    def run(rendered, task):
        if task.id in fail_ids:
            raise RuntimeError("provider down")
        return "good" if task.meta["rule"] in rendered else "bad"

    def reward(task, output):
        return 1.0 if output == "good" else 0.0

    def propose(rendered, task, output, reward):
        return None if flat else task.meta["rule"]

    return PilotPolicy(tasks=train, test_tasks=test, reward=reward, run=run,
                       propose=propose, strategy=AppendRules(),
                       artifact_id="skill")


def _config(**kw):
    base = dict(rounds=8, n_workers=3, max_concurrency=3, contaminated=False)
    base.update(kw)
    return PilotConfig(**base)


def test_a_strong_gain_on_a_disjoint_test_split_promotes():
    report = pilot(_policy(), _config())

    assert report.status == "decided"
    assert report.action == PromotionAction.PROMOTE
    assert report.error is None
    assert report.evidence.eval_result.baseline == 0.0
    assert report.evidence.eval_result.score == 1.0
    assert report.evidence.eval_result.n == 12
    assert report.evidence.artifact_changed is True
    assert report.manifest is not None
    assert report.manifest.manifest_id


def test_dry_run_makes_no_model_call_and_validates_the_split():
    calls = {"n": 0}
    policy = _policy()
    counted = policy.run

    def run(rendered, task):
        calls["n"] += 1
        return counted(rendered, task)

    policy = PilotPolicy(tasks=policy.tasks, test_tasks=policy.test_tasks,
                         reward=policy.reward, run=run,
                         propose=policy.propose, strategy=policy.strategy,
                         artifact_id=policy.artifact_id)
    report = pilot(policy, _config(dry_run=True))

    assert calls["n"] == 0
    assert report.status == "planned"
    assert report.action is None
    assert report.before == {} and report.after == {}
    assert report.manifest is not None
    assert "no model call" in report.notes[0]


def test_an_unchanged_artifact_is_noise_only_and_cannot_promote():
    report = pilot(_policy(flat=True), _config())

    assert report.action != PromotionAction.PROMOTE
    assert report.evidence.noise_only is True
    assert report.evidence.gain == 0.0
    assert report.evidence.eval_result.passed is False


def test_a_contaminated_dataset_is_rejected_before_any_call():
    calls = {"n": 0}
    base = _policy()

    def run(rendered, task):
        calls["n"] += 1
        return base.run(rendered, task)

    policy = PilotPolicy(tasks=base.tasks, test_tasks=base.test_tasks,
                         reward=base.reward, run=run,
                         propose=base.propose, strategy=base.strategy,
                         artifact_id=base.artifact_id)
    report = pilot(policy, _config(contaminated=True))

    assert calls["n"] == 0
    assert report.action == PromotionAction.REJECT
    assert any("contaminated" in reason for reason in report.decision.reasons)


def test_a_missing_contamination_check_defers():
    report = pilot(_policy(), _config(contaminated=None))

    assert report.action == PromotionAction.DEFER
    assert "contamination" in report.decision.missing
    assert any("contamination was not checked" in note
               for note in report.notes)


def test_an_overlapping_test_split_is_refused_before_any_call():
    policy = _policy()
    overlap = list(policy.tasks[:2])
    called = {"n": 0}

    def run(rendered, task):
        called["n"] += 1
        return "good"

    bad = PilotPolicy(tasks=policy.tasks, test_tasks=overlap + list(
        policy.test_tasks), reward=policy.reward, run=run,
        propose=policy.propose, strategy=policy.strategy, artifact_id="skill")
    report = pilot(bad, _config())

    assert called["n"] == 0
    assert report.status == "refused"
    assert report.decision is None
    assert "overlaps" in report.error


def test_a_high_test_failure_rate_censors_the_measurement():
    report = pilot(_policy(fail_ids={f"test-{i}" for i in range(8)}), _config())

    assert report.action != PromotionAction.PROMOTE
    assert report.evidence.run_health is not None
    assert report.evidence.run_health.failed == 8
    assert report.evidence.run_health.attempted == 12
    assert report.evidence.run_health.censored is True
    assert any("run health" in note for note in report.notes)


def test_the_report_is_json_serializable_and_has_a_stable_markdown_card():
    report = pilot(_policy(), _config())

    payload = report.to_dict()
    assert payload["schema_version"] == 1
    assert payload["status"] == "decided"
    assert payload["decision"]["action"] == "promote"
    assert payload["manifest"]["manifest_id"] == report.manifest.manifest_id
    json.dumps(payload)

    card = report.to_markdown()
    assert card.startswith("# Pilot: skill\n")
    assert "Decision: **PROMOTE**" in card
    assert "Manifest:" in card
    assert "Next:" in card


def test_two_seeds_pool_the_same_test_tasks():
    report = pilot(_policy(), _config(seeds=(0, 1)))

    assert report.action == PromotionAction.PROMOTE
    assert report.evidence.eval_result.n == 24
    assert [row["seed"] for row in report.run["per_seed"]] == [0, 1]
    assert any("pool every seed" in note for note in report.notes)


def test_same_inputs_produce_the_same_manifest_id():
    first = pilot(_policy(), _config(dry_run=True))
    second = pilot(_policy(), _config(dry_run=True))

    assert first.manifest.manifest_id == second.manifest.manifest_id


def test_pilot_scores_composes_the_same_decision_without_a_run():
    before = {f"t{i}": 0.0 for i in range(20)}
    after = {f"t{i}": 1.0 for i in range(20)}
    report = pilot_scores(before, after,
                          config=PilotConfig(contaminated=False))

    assert report.action == PromotionAction.PROMOTE
    assert report.evidence.eval_result.n == 20
    assert report.evidence.gain == 1.0
