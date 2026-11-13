"""The optional search recipe must save work without inventing model credit."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from agentdescent.aggregator import AggregatorConfig, install_policy
from agentdescent.artifact_search import ArtifactSearch
from agentdescent.async_evolve import async_evolve
from agentdescent.evolution import EvolvingArtifact, SingleSlot, Task, evolve
from agentdescent.evolvable import Diff, EvidenceCard
from agentdescent.model_router import ModelSpec
from agentdescent.policies import AcceptDecision, MergeContext, Policies, ProposalContext
from agentdescent.treestrategy import FileTree


class _Allow:
    def accept(self, ctx):
        return AcceptDecision(True)


_allow = _Allow()


def _search(**kwargs):
    return ArtifactSearch(
        [ModelSpec("small", cost=1), ModelSpec("large", cost=4)],
        {"small": lambda *args: "small proposal",
         "large": lambda *args: "large proposal"}, **kwargs)


def _propose(search):
    return search.propose(ProposalContext(
        rendered="seed", task=Task("t", "question"), output="wrong", reward=0.0))[0]


def _artifact(state=None, strategy=None):
    return EvolvingArtifact("a", state or {"value": "seed"},
                            strategy=strategy or SingleSlot())


def _card(proposal, artifact=None, ops=None):
    artifact = artifact or _artifact()
    diff = Diff(proposal.proposal_id, artifact.id,
                ops if ops is not None else {"value": proposal.text})
    return EvidenceCard(diff, {artifact.id: artifact.version}, [artifact.id],
                        proposal_id=proposal.proposal_id)


def _context(card, *, artifact=None, cards=None, gain=0.5, diff=None):
    artifact = artifact or _artifact()
    return MergeContext(
        artifact=artifact, candidate=artifact.apply(diff or card.diff),
        cards=[card] if cards is None else cards, diff=diff or card.diff,
        base_counts=(1, 3), cand_counts=(1 + 4 * gain, 3 - 4 * gain))


def _counts(search):
    return search.report()["counters"]


def _arms(search):
    return {row["model"]: row for row in search.report()["routing"]["models"]}


def test_recipe_forwards_acceptance_install_hooks_and_decision():
    class Gate:
        screen_rejections = 0

        def bind(self, verifier):
            self.verifier = verifier

        def configure(self, config):
            self.config = config

        def accept(self, ctx):
            return AcceptDecision(False, "below-threshold", "fixture veto")

        def on_screen_reject(self):
            self.screen_rejections += 1

    gate = Gate()
    search = _search(acceptance=gate)
    policies = search.policies()
    assert policies.proposal is search
    assert policies.screen is search
    assert policies.acceptance is search
    verifier, config = object(), AggregatorConfig()
    install_policy(search, verifier, config)
    assert gate.verifier is verifier and gate.config is config
    search.on_screen_reject()
    assert gate.screen_rejections == 1
    card = _card(_propose(search))
    decision = search.accept(_context(card))
    assert not decision.accept and decision.detail == "fixture veto"


def test_delayed_feedback_is_attributed_to_the_original_model_once():
    search = _search(acceptance=_allow)
    small, large = _propose(search), _propose(search)
    assert small.text == "small proposal" and large.text == "large proposal"
    assert small.proposal_id and small.proposal_id != large.proposal_id
    large_ctx = _context(_card(large), gain=0.75)
    search.accept(large_ctx)
    search.accept(_context(_card(small), gain=0.25))
    search.accept(large_ctx)
    arms = _arms(search)
    assert arms["small"]["pulls"] == arms["large"]["pulls"] == 1
    assert arms["small"]["mean_reward"] == pytest.approx(0.25)
    assert arms["large"]["mean_reward"] == pytest.approx(0.75)
    assert _counts(search)["feedback"] == 2
    assert search.report()["pending"] == 0


def test_parallel_generation_does_not_hold_a_lock_across_callbacks():
    rendezvous = threading.Barrier(2)

    def proposal(text):
        def generate(*args):
            rendezvous.wait(timeout=10)
            return text
        return generate

    search = ArtifactSearch(
        [ModelSpec("a", 1), ModelSpec("b", 1)],
        {"a": proposal("from a"), "b": proposal("from b")}, acceptance=_allow)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(_propose, search) for _ in range(2)]
        proposals = [f.result(timeout=15) for f in futures]
    assert {p.text for p in proposals} == {"from a", "from b"}
    assert len({p.proposal_id for p in proposals}) == 2
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda p: search.accept(_context(_card(p))), proposals))
    assert _counts(search)["feedback"] == 2
    assert search.report()["routing"]["pulls"] == 2


def test_mixed_fusion_and_mismatched_diff_receive_no_model_credit():
    search = _search(acceptance=_allow)
    first, second = _card(_propose(search)), _card(_propose(search))
    fused = Diff("fused", "a", {"value": "combined proposal"})
    search.accept(_context(first, cards=[first, second], diff=fused))
    first, second = _card(_propose(search)), _card(_propose(search))
    search.accept(_context(first, diff=second.diff))
    assert _counts(search)["feedback"] == 0
    assert search.report()["routing"]["pulls"] == 0


def test_negative_measured_gain_is_clipped_to_zero():
    search = _search(acceptance=_allow)
    search.accept(_context(_card(_propose(search)), gain=-0.25))
    assert _arms(search)["small"]["mean_reward"] == 0.0


def test_exact_duplicate_is_batch_local_and_does_not_poison_retries():
    search = _search()
    artifact = _artifact()
    card = _card(_propose(search))
    search.begin_batch(artifact)
    assert search.screen(card) is None
    assert search.screen(card) is not None
    # The previous batch may have been stale, rejected, or interrupted.
    search.begin_batch(artifact)
    assert search.screen(card) is None
    assert _counts(search)["duplicates"] == 1


def test_old_card_cannot_suppress_a_fresh_candidate_before_staleness_filtering():
    search = _search()
    artifact = _artifact()
    artifact.version = 20
    old = _card(_propose(search), artifact, {"value": "improved"})
    old.base_version = {"a": 1}
    fresh = _card(_propose(search), artifact, {"value": "improved"})
    search.begin_batch(artifact)
    assert search.screen(old) is None
    assert search.screen(fresh) is None


def test_filetree_screen_compares_full_candidate_with_deletions():
    search = _search()
    artifact = _artifact({"a.py": "x = 0\n", "b.py": "y = 1\n"}, FileTree())
    proposal = _propose(search)
    search.begin_batch(artifact)
    deleted = _card(proposal, artifact, {"a.py": "x = 2\n", "b.py": None})
    preserved = _card(proposal, artifact, {"a.py": "x = 2\n"})
    assert search.screen(deleted) is None
    assert search.screen(preserved) is None
    # An explicit no-op on an untouched file produces the same complete tree.
    equivalent = _card(proposal, artifact, {"a.py": "x = 2\n", "b.py": "y = 1\n"})
    assert search.screen(equivalent) is not None


def test_near_duplicate_screen_is_opt_in_and_not_semantic_equivalence():
    common = "\n".join(f"value_{i} = input_value + {i}" for i in range(80))
    texts = [common + "\nresult = 1", common + "\nresult = 2"]
    for threshold, rejected in ((None, False), (0.8, True)):
        search = _search(similarity_threshold=threshold)
        proposal = _propose(search)
        search.begin_batch(_artifact())
        assert search.screen(_card(proposal, ops={"value": texts[0]})) is None
        assert (search.screen(_card(proposal, ops={"value": texts[1]})) is not None) is rejected
    # Trusted fixture programs differ in result despite sharing almost every token.
    results = []
    for text in texts:
        namespace = {"input_value": 0}
        exec(text, namespace)
        results.append(namespace["result"])
    assert results == [1, 2]


def test_pending_history_is_bounded_and_evicted_feedback_is_not_misattributed():
    search = _search(acceptance=_allow, max_pending=2)
    oldest = _propose(search)
    _propose(search)
    newest = _propose(search)
    assert search.report()["pending"] == 2
    assert _counts(search)["evicted"] == 1
    search.accept(_context(_card(oldest)))
    assert _counts(search)["feedback"] == 0
    search.accept(_context(_card(newest)))
    assert _counts(search)["feedback"] == 1


def test_failed_and_empty_generation_are_accounted_without_pending_tickets():
    def broken(*args):
        raise RuntimeError("fixture backend unavailable")

    search = ArtifactSearch([ModelSpec("broken", 2), ModelSpec("empty", 3)],
                            {"broken": broken, "empty": lambda *a: None})
    with pytest.raises(RuntimeError, match="fixture backend"):
        _propose(search)
    assert not search.propose(ProposalContext("seed", Task("t", "q"), "wrong", 0.0))
    report = search.report()
    assert report["pending"] == 0
    assert report["counters"]["generation_failures"] == 1
    assert report["counters"]["empty"] == 1
    assert report["configured_cost"] == 5
    assert report["generation_seconds"] >= 0
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_recipe_is_connected_to_the_real_engine(asynchronous, tmp_path):
    search = ArtifactSearch([ModelSpec("offline", 1)],
                            {"offline": lambda *args: "answer correctly"})
    tasks = [Task(str(i), "q") for i in range(12)]
    common = dict(run=lambda text, task: "yes" if "correctly" in text else "no",
                  strategy=SingleSlot(initial_value="seed"), policies=search.policies(),
                  self_verify=False, held_out_frac=0.5, n_workers=2,
                  repo_path=str(tmp_path / "ledger"), seed=7,
                  agg_config=AggregatorConfig(batch_trigger=2, max_wait_rounds=1))
    if asynchronous:
        result = async_evolve(tasks, lambda t, o: float(o == "yes"),
                              max_iters=8, max_seconds=30, **common)
    else:
        result = evolve(tasks, lambda t, o: float(o == "yes"), rounds=2, **common)
    assert result.error is None
    assert result.final_reward == 1.0
    assert "correctly" in result.rendered
    assert _counts(search)["generated"] >= 1
    assert _counts(search)["feedback"] >= 1


def test_duplicate_screen_reduces_real_tournament_evaluations(tmp_path):
    class Uncached:
        def get_or_eval(self, key, fn):
            return fn()

    def run_case(screened):
        calls = []
        search = ArtifactSearch([ModelSpec("offline", 1)],
                                {"offline": lambda *args: "correct"}, acceptance=_allow)
        policies = search.policies() if screened else Policies(acceptance=_allow)
        policies.eval_cache = Uncached()

        def run(text, task):
            calls.append((text, task.id))
            return text

        result = evolve(
            [Task(str(i), "q") for i in range(12)], lambda t, o: float(o == "correct"),
            run=run, propose=None if screened else lambda *args: "correct",
            strategy=SingleSlot(initial_value="seed"), policies=policies,
            rounds=1, n_workers=4, self_verify=False, held_out_frac=0.5,
            repo_path=str(tmp_path / str(screened)), seed=0,
            agg_config=AggregatorConfig(batch_trigger=4, fusion_tournament=True))
        assert result.error is None and result.final_reward == 1.0
        return sum(text == "correct" for text, _ in calls), search

    plain_calls, _ = run_case(False)
    screened_calls, search = run_case(True)
    assert _counts(search)["duplicates"] == 3
    assert screened_calls < plain_calls
