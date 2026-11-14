"""Failure-stratified sampling: coverage, disjoint splits and transfer (#946).

A search set dominated by one failure mode teaches the proposer that mode, and
the gain vanishes on held-out tasks. These tests pin the two properties that
make the sampler useful: every stratum is sampled, and the search / select /
final sets cannot leak into one another.
"""

import pytest

from agentdescent.sampling import (
    DifficultyWeighted,
    FailureStratifiedSampler,
    RoundRobin,
    TaskSampler,
    TaskSplit,
)


def _three_strata():
    labels = {}
    for i in range(10):
        labels[f"timeout-{i}"] = "timeout"
        labels[f"format-{i}"] = "format"
        labels[f"logic-{i}"] = "logic"
    return labels


def test_failure_stratified_sampler_satisfies_the_protocol():
    assert isinstance(FailureStratifiedSampler(), TaskSampler)


def test_existing_samplers_are_untouched():
    assert isinstance(RoundRobin(), TaskSampler)
    assert isinstance(DifficultyWeighted(), TaskSampler)
    assert RoundRobin().pick(["a", "b"], 3) == "b"


def test_three_strata_are_all_covered_and_none_is_starved():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels, min_per_stratum=2)
    sampler.split(ids)
    for i in range(30):
        sampler.pick(ids, i)

    report = sampler.report()
    assert set(report.coverage) == {"timeout", "format", "logic"}
    assert report.starved == ()
    assert report.ignored == ()
    for coverage in report.coverage.values():
        assert coverage.search > 0
        assert coverage.picks >= 2, coverage


def test_split_is_three_way_disjoint_by_construction():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(ids)

    assert split.is_disjoint()
    assert split.overlap() == {}
    assert set(split.all_ids()) == set(ids)
    assert len(split.all_ids()) == len(ids)
    assert not (set(split.search) & set(split.select))
    assert not (set(split.search) & set(split.final))
    assert not (set(split.select) & set(split.final))
    assert sampler.report().overlap == {}


def test_pick_never_returns_a_hidden_task():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(ids)
    hidden = set(split.select) | set(split.final)

    for i in range(40):
        picked = sampler.pick(ids, i)
        assert picked in split.search
        assert picked not in hidden

    with pytest.raises(ValueError, match="no search task"):
        sampler.pick(list(hidden), 0)


def test_a_leak_is_detected_and_fails_the_split():
    """Disjointness is enforced on assignment; the report still proves it."""
    leaky = TaskSplit(search=("a", "b"), select=("b",), final=("c",))
    assert not leaky.is_disjoint()
    assert leaky.overlap() == {"b": ("search", "select")}


def test_a_dominant_stratum_gets_a_coverage_warning():
    labels = {f"timeout-{i}": "timeout" for i in range(18)}
    labels.update({"format-0": "format", "logic-0": "logic"})
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    sampler.split(ids)
    for i in range(12):
        sampler.pick(ids, i)

    report = sampler.report()
    assert "timeout" in report.dominant
    assert any("dominant" in warning and "timeout" in warning
               for warning in report.warnings)


def test_a_stratum_the_run_never_samples_is_flagged():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    sampler.split(ids)
    timeout_ids = [task_id for task_id, label in labels.items()
                   if label == "timeout"]
    for i in range(6):
        sampler.pick(timeout_ids, i)

    report = sampler.report()
    assert set(report.ignored) == {"format", "logic"}
    assert any("ignored" in warning for warning in report.warnings)


def test_transfer_status_sees_a_selection_gain_that_does_not_hold():
    labels = _three_strata()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    for task_id in split.select:
        sampler.record(task_id, 0.9)
    for task_id in split.final:
        sampler.record(task_id, 0.4)

    transfer = sampler.report().transfer
    assert transfer.status == "degrades"
    assert transfer.select_n == len(split.select)
    assert transfer.final_n == len(split.final)
    assert transfer.gap == pytest.approx(0.5)
    assert any("does not transfer" in warning
               for warning in sampler.report().warnings)


def test_transfer_status_holds_when_the_final_set_agrees():
    labels = _three_strata()
    sampler = FailureStratifiedSampler(labels)
    split = sampler.split(list(labels))
    for task_id in split.select:
        sampler.record(task_id, 0.8)
    for task_id in split.final:
        sampler.record(task_id, 0.8)

    transfer = sampler.report().transfer
    assert transfer.status == "holds"
    assert transfer.gap == pytest.approx(0.0)


def test_a_callable_signature_and_seed_are_deterministic():
    ids = [f"timeout-{i}" for i in range(4)]
    ids += [f"format-{i}" for i in range(4)]
    ids += [f"logic-{i}" for i in range(4)]

    def signature(task_id):
        return task_id.split("-")[0]

    first = FailureStratifiedSampler(signature, tasks=ids, seed=7)
    second = FailureStratifiedSampler(signature, tasks=ids, seed=7)
    assert first.split(ids) == second.split(ids)
    assert set(first.report().coverage) == {"timeout", "format", "logic"}


def test_a_task_never_moves_split_when_new_ids_arrive():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels)
    before = sampler.split(ids)
    after = sampler.split(ids + ["late-0"])
    assert after.search[:len(before.search)] == before.search or \
        set(before.search) <= set(after.search)
    assert set(before.select) <= set(after.select)
    assert set(before.final) <= set(after.final)


def test_min_per_stratum_is_configurable():
    labels = _three_strata()
    ids = list(labels)
    sampler = FailureStratifiedSampler(labels, min_per_stratum=3)
    sampler.split(ids)
    for i in range(9):
        sampler.pick(ids, i)
    assert all(coverage.picks >= 3
               for coverage in sampler.report().coverage.values())
