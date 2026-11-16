"""Proposal identity survives adapters, workers and the pre-evaluation gate."""

from dataclasses import FrozenInstanceError, dataclass

import pytest

from agentdescent import policies
from agentdescent.aggregator import Aggregator, AggregatorConfig
from agentdescent.async_evolve import async_evolve
from agentdescent.domains.router import (
    RouterSkill, deserialize_router, serialize_router,
)
from agentdescent.evolvable import Diff, EvidenceCard
from agentdescent.evolution import (
    ProposalContractError, SingleSlot, Task, _checked_proposal,
    _propose_via_policy, evolve,
)
from agentdescent.ledger import Ledger
from agentdescent.policies import Policies, ScreenPolicy
from agentdescent.scheduler import AuditScheduler
from agentdescent.verifier import ThreeLayerVerifier


@dataclass(frozen=True)
class _ProposalBeforeSupport:
    text: str
    proposal_id: str


def _proposal(text, proposal_id):
    # The baseline must exercise rejection, not stop at an import error.
    cls = getattr(policies, "Proposal", _ProposalBeforeSupport)
    return cls(text, proposal_id)


def test_proposal_identity_is_immutable():
    proposal = policies.Proposal("candidate", "model-a:1")
    with pytest.raises(FrozenInstanceError):
        proposal.proposal_id = "model-b:1"


def test_adapters_preserve_distinct_identities_for_identical_text():
    one = _proposal("same candidate", "model-a:1")
    two = _proposal("same candidate", "model-b:1")

    class Proposer:
        k = 3

        def propose(self, ctx):
            return [one, two, "legacy", None, _proposal("", "empty")]

    task = Task("t", "question")
    output = _propose_via_policy(Proposer())("seed", task, "answer", 0.0)
    checked = _checked_proposal(output, task)
    assert checked == [one, two, "legacy"]
    assert checked[0] is one and checked[1] is two
    assert _checked_proposal(one, task) == [one]
    assert _checked_proposal((one, "legacy"), task) == [one, "legacy"]


@pytest.mark.parametrize("value", [42, ["candidate", 42]])
def test_non_text_proposals_remain_contract_errors(value):
    with pytest.raises(ProposalContractError):
        _checked_proposal(value, Task("t", "question"))


@pytest.mark.parametrize("text,identity", [(42, "model:1"), ("candidate", 42)])
def test_invalid_proposal_fields_remain_contract_errors(text, identity):
    proposal = _proposal(text, identity)
    with pytest.raises(ProposalContractError):
        _checked_proposal(proposal, Task("t", "question"))


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("via_policy", [False, True])
def test_workers_pass_text_to_strategy_and_identity_to_screen(
        tmp_path, asynchronous, via_policy):
    seen = []
    strategy_inputs = []

    class Proposer:
        k = 3

        def propose(self, ctx):
            return [_proposal("same", "a:1"), _proposal("same", "b:1"), "legacy"]

    class TextStrategy(SingleSlot):
        def to_diff(self, state, proposal, author, base_version, target):
            strategy_inputs.append(proposal)
            assert type(proposal) is str
            return super().to_diff(state, proposal, author, base_version, target)

    class RejectScreen:
        def screen(self, card):
            seen.append((card.proposal_id, card.diff.ops))
            return "fixture: no held-out evaluation needed"

    kwargs = dict(
        tasks=[Task(f"t{i}", "question") for i in range(8)],
        reward=lambda task, output: 0.0,
        run=lambda rendered, task: "answer",
        strategy=TextStrategy(initial_value="seed"),
        policies=Policies(screen=RejectScreen()),
        n_workers=1, held_out_frac=0.5, self_verify=False,
        repo_path=str(tmp_path / "repo"),
    )
    if via_policy:
        kwargs["policies"].proposal = Proposer()
    else:
        kwargs["propose"] = lambda rendered, task, output, score: Proposer().propose(None)
    if asynchronous:
        result = async_evolve(**kwargs, max_iters=1, max_seconds=10)
    else:
        result = evolve(**kwargs, rounds=1)
    assert result.error is None, result.error
    assert strategy_inputs == ["same", "same", "legacy"]
    assert [identity for identity, _ in seen] == ["a:1", "b:1", ""]
    assert seen[0][1] == seen[1][1]


def test_rebase_preserves_identity_and_legacy_cards_default_to_empty():
    diff = Diff("d", "artifact", {"value": "candidate"})
    assert EvidenceCard(diff, {"artifact": 1}, ["artifact"]).proposal_id == ""
    card = EvidenceCard(diff, {"artifact": 1}, ["artifact"], proposal_id="a:1")
    rebased = card.rebased_onto({"artifact": 2})
    assert rebased.proposal_id == "a:1"
    assert rebased.base_version == {"artifact": 2}
    assert card.base_version == {"artifact": 1}


def test_screen_receives_each_batch_artifact_before_its_cards(tmp_path):
    events = []

    class BatchScreen:
        def begin_batch(self, artifact):
            self.artifact = artifact
            self.seen = []
            events.append(("begin", artifact.id))

        def screen(self, card):
            assert self.artifact.id == card.diff.target
            candidate = self.artifact.apply(card.diff)
            assert candidate.table == card.diff.ops
            self.seen.append(card.diff.diff_id)
            events.append(("screen", tuple(self.seen)))
            return "fixture: screened before evaluation"

    screen = BatchScreen()
    assert isinstance(screen, ScreenPolicy)
    ledger = Ledger(str(tmp_path / "repo"), serialize_router, deserialize_router)
    try:
        ledger.register(RouterSkill("a", table={}))
        ledger.register(RouterSkill("b", table={}))
        verifier = ThreeLayerVerifier(lambda artifact, tasks: pytest.fail("screened"), [])
        aggregator = Aggregator(ledger, verifier, AuditScheduler(),
                                AggregatorConfig(), screen=screen)
        for target, ids in [("a", ["first", "second"]), ("b", ["third"])]:
            cards = [EvidenceCard(Diff(identity, target, {"kw": identity}),
                                  {target: 1}, [target]) for identity in ids]
            result = aggregator._prepare(target, cards=cards)
            assert result.category == "critic-rejected"
        assert events == [
            ("begin", "a"), ("screen", ("first",)),
            ("screen", ("first", "second")),
            ("begin", "b"), ("screen", ("third",)),
        ]
    finally:
        ledger.close()
