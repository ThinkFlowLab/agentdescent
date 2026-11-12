"""Falsification-gated lesson admission (#938).

The gate's whole claim is that "it improved the held-out count" is not enough:
a lesson has to transfer to the *target* partition, must not regress an
*archived* task, and must not move a verdict on the *falsification* partition --
the tasks the lesson is not supposed to apply to. A lesson that moves those
verdicts is over-broad, and a lesson that only helps the task it was proposed on
has not transferred at all.

The probes are supplied by the caller in v1 (``FalsificationAcceptance(
target=…, falsification=…, archived=…)``); the aggregator adds the evaluator.
The fake evaluator here is per-task, offline, and deterministic, so the tests
pin the *decision rule* rather than a model's mood.
"""

from dataclasses import dataclass, field
from typing import Dict, Sequence

import pytest

from agentdescent.aggregator import Aggregator, AggregatorConfig
from agentdescent.defaults import DefaultAcceptance
from agentdescent.evolvable import Diff, EvidenceCard
from agentdescent.evolution import Task
from agentdescent.acceptance import (
    FalsificationAcceptance, ProbeContext, ProbePartitions,
)
from agentdescent.ledger import Ledger
from agentdescent.policies import AcceptDecision, MergeContext
from agentdescent.scheduler import AuditScheduler
from agentdescent.verifier import ThreeLayerVerifier, VerifierBudget


# -- fakes ------------------------------------------------------------------


@dataclass
class FakeArtifact:
    id: str = "lesson"
    state: Dict[str, str] = field(default_factory=dict)
    version: int = 1
    blast_radius: float = 0.2


def _task(tid: str) -> Task:
    return Task(tid, f"prompt for {tid}")


def _probes(scores: Dict[str, Dict[str, float]]) -> ProbeContext:
    """``scores[artifact_id][task_id] -> reward``, the fake per-task evaluator."""
    target = (_task("tgt-1"), _task("tgt-2"))
    falsification = (_task("fal-1"), _task("fal-2"))
    archived = (_task("arc-1"), _task("arc-2"))

    def evaluate(artifact, tasks):
        table = scores[artifact.id]
        return {t.id: table[t.id] for t in tasks}

    return ProbeContext(target=target, falsification=falsification,
                        archived=archived, evaluate=evaluate)


def _ctx(probes, *, base_artifact=None, cand_artifact=None) -> MergeContext:
    base = base_artifact or FakeArtifact("base")
    cand = cand_artifact or FakeArtifact("cand")
    return MergeContext(
        artifact=base, candidate=cand, cards=[],
        base_counts=(1.0, 1.0), cand_counts=(2.0, 0.0),
        diff=Diff(diff_id="d-1", target="lesson", ops={"rule": "x"}),
        probes=probes)


def _policy() -> FalsificationAcceptance:
    parts = ProbePartitions(target=(_task("tgt-1"), _task("tgt-2")),
                            falsification=(_task("fal-1"), _task("fal-2")),
                            archived=(_task("arc-1"), _task("arc-2")))
    return FalsificationAcceptance(target=parts.target,
                                   falsification=parts.falsification,
                                   archived=parts.archived)


# -- the four admission rules ------------------------------------------------


def test_a_lesson_that_only_helps_its_source_task_is_rejected():
    """No gain on the target partition: the lesson did not transfer."""
    probes = _probes({
        "base": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 0.0,
                 "arc-1": 1.0, "arc-2": 1.0},
        "cand": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 0.0,
                 "arc-1": 1.0, "arc-2": 1.0},
    })
    decision = _policy().accept(_ctx(probes))
    assert decision.accept is False
    assert decision.category == "no-target-transfer"
    assert "tgt-1" in decision.detail and "tgt-2" in decision.detail


def test_a_lesson_that_regresses_an_archived_task_is_rejected():
    """It transfers, but it breaks something that used to work."""
    probes = _probes({
        "base": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 0.0,
                 "arc-1": 1.0, "arc-2": 1.0},
        "cand": {"tgt-1": 1.0, "tgt-2": 1.0, "fal-1": 0.0, "fal-2": 0.0,
                 "arc-1": 0.0, "arc-2": 1.0},
    })
    decision = _policy().accept(_ctx(probes))
    assert decision.accept is False
    assert decision.category == "archived-regression"
    assert "arc-1" in decision.detail


def test_a_lesson_that_changes_a_falsification_verdict_is_rejected():
    """It transfers and regresses nothing, but it is over-broad: it moves a
    verdict on a task it was never meant to touch."""
    probes = _probes({
        "base": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
        "cand": {"tgt-1": 1.0, "tgt-2": 1.0, "fal-1": 1.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
    })
    decision = _policy().accept(_ctx(probes))
    assert decision.accept is False
    assert decision.category == "falsification-moved"
    assert "fal-1" in decision.detail and "fal-2" not in decision.detail


def test_a_good_lesson_commits_with_provenance():
    probes = _probes({
        "base": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
        "cand": {"tgt-1": 1.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
    })
    policy = _policy()
    decision = policy.accept(_ctx(probes))
    assert decision.accept is True
    assert decision.category == "committed"
    assert decision.provenance is not None
    record = decision.provenance
    for key in ("rule_id", "precondition", "behavior_change", "expected_effect",
                "verifier", "trace_ids", "evidence_card_hash"):
        assert key in record, key
    assert record["rule_id"] == "d-1"
    assert record["behavior_change"] == ["rule"]
    assert set(record["expected_effect"]) >= {"base", "candidate"}


# -- the honest fallback -----------------------------------------------------


def test_missing_probes_defer_instead_of_rejecting_or_weakening():
    decision = _policy().accept(_ctx(None))
    assert decision.accept is False
    assert decision.defer is True
    assert decision.category == "probes-unavailable"
    assert "defer" in decision.detail.lower()


def test_default_acceptance_is_untouched_by_the_new_field():
    """The probes ride along; the shipped gate must not start reading them."""
    policy = DefaultAcceptance(base_delta=0.5, anneal_half_life=10,
                               accept_samples=200)
    ctx = _ctx(_probes({"base": {}, "cand": {}}))
    decision = policy.accept(ctx)
    assert decision.accept is True
    assert decision.category == "committed"


# -- the aggregator supplies the evaluator, only when asked ------------------


def _aggregator(tmp_path, acceptance):
    ledger = Ledger(str(tmp_path / "repo"), serialize=lambda a: {"state": {}},
                    deserialize=lambda aid, v, d: None)
    verifier = ThreeLayerVerifier(
        eval_fn=lambda artifact, tasks: 1.0,
        held_out=[_task("held-1")],
        budget=VerifierBudget(oracle_calls_remaining=5))
    return Aggregator(ledger, verifier, AuditScheduler(), AggregatorConfig(),
                      acceptance=acceptance)


def test_the_aggregator_populates_probes_only_for_a_policy_that_needs_them(tmp_path):
    asking = _aggregator(tmp_path, _policy())
    probes = asking._probe_context()
    assert probes is not None
    assert [t.id for t in probes.target] == ["tgt-1", "tgt-2"]
    assert [t.id for t in probes.falsification] == ["fal-1", "fal-2"]
    assert [t.id for t in probes.archived] == ["arc-1", "arc-2"]
    assert probes.evaluate(FakeArtifact("base"), probes.target) == {
        "tgt-1": 1.0, "tgt-2": 1.0}

    default = _aggregator(tmp_path, DefaultAcceptance())
    assert default._probe_context() is None


def test_the_commit_record_is_the_shape_the_shared_writer_takes():
    """The gate produces the record; the *writer* belongs to #966.

    ``agentdescent.falsification.append_provenance`` keeps records under
    ``<ledger>/.git/provenance/`` and requires only a ``rule_id``; its own
    behaviour is tested in ``tests/test_provenance_outside_worktree.py``. What
    is asserted here is only that the aggregator hands it a usable record --
    a mapping with a stable ``rule_id`` -- so the two halves meet.
    """
    probes = _probes({
        "base": {"tgt-1": 0.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
        "cand": {"tgt-1": 1.0, "tgt-2": 0.0, "fal-1": 0.0, "fal-2": 1.0,
                 "arc-1": 1.0, "arc-2": 1.0},
    })
    record = _policy().accept(_ctx(probes)).provenance
    assert isinstance(record, dict)
    assert isinstance(record["rule_id"], str) and record["rule_id"]
