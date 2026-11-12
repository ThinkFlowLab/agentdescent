"""Every decision records the policy version that produced it (#943).

`Policies` is read once at `evolve()` entry and never recorded. A commit
therefore carries the artifact state and the diff, but not which
acceptance/conflict/fusion/staleness bundle admitted it -- so a three-line policy
change moves the acceptance rate and the ledger cannot separate the commits
admitted under the old bundle from the new one (#52).

The digest is content-addressed over the bundle plus the decision-relevant
config, additive everywhere it lands, and must never be able to change the
behaviour of a run.
"""

import json
import os

from agentdescent.aggregator import AggregatorConfig, merge_commit_message
from agentdescent.decisions import DecisionLog, DecisionRecord
from agentdescent.evolvable import Diff
from agentdescent.manifest import RunManifest, build_manifest
from agentdescent.policies import MergeContext, Policies
from agentdescent.evolvespec import EvolveSpec


def _diff() -> Diff:
    return Diff(diff_id="w0:abc:1", target="skill", ops={"k": "v"}, author="t")


def _spec() -> EvolveSpec:
    return EvolveSpec(kind="text", target="hi", data={"inline": [{"prompt": "q", "gold": "a"}]})


def _payloads(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_a_written_decision_carries_the_policy_version(tmp_path):
    log = DecisionLog(str(tmp_path / "decisions.jsonl"))
    log.record(kind="merge", artifact_id="skill", diff_id="w0:abc:1", accepted=True,
               category="committed")
    stored = _payloads(log.path)
    assert stored
    assert "policy_digest" in stored[0]          # the decision names its policy
    digest = stored[0]["policy_digest"]
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_the_same_decision_under_two_policies_is_distinguishable(tmp_path):
    from agentdescent.policies import policy_digest

    strict = policy_digest(Policies(), config=AggregatorConfig(base_delta=0.05))
    loose = policy_digest(Policies(), config=AggregatorConfig(base_delta=0.75))
    assert strict != loose
    log = DecisionLog(str(tmp_path / "d.jsonl"))
    a = log.record(kind="merge", artifact_id="skill", accepted=True,
                   policy_digest=strict)
    b = log.record(kind="merge", artifact_id="skill", accepted=True,
                   policy_digest=loose)
    assert a.policy_digest == strict and b.policy_digest == loose
    assert a.policy_digest != b.policy_digest


def test_a_policy_change_between_decisions_leaves_a_parent_edge(tmp_path):
    log = DecisionLog(str(tmp_path / "d.jsonl"))
    first = log.record(kind="merge", artifact_id="skill", accepted=True,
                       policy_digest="a" * 64)
    second = log.record(kind="merge", artifact_id="skill", accepted=True,
                        policy_digest="b" * 64)
    third = log.record(kind="merge", artifact_id="skill", accepted=False,
                       policy_digest="b" * 64)
    assert second.parent_id == first.record_id
    assert second.evidence["policy_change"] == {"from": "a" * 64, "to": "b" * 64}
    # Unchanged digest: no new edge, so the chain is the policy history only.
    assert third.parent_id is None


def test_the_digest_is_stable_and_order_independent():
    from agentdescent.policies import policy_digest

    assert policy_digest(Policies()) == policy_digest(Policies())
    assert policy_digest(Policies()) == policy_digest(None)
    assert policy_digest(Policies(), config=AggregatorConfig()) == \
        policy_digest(Policies(), config=AggregatorConfig())


def test_a_custom_policy_class_changes_the_digest():
    from agentdescent.policies import policy_digest

    class _MyAcceptance:
        def accept(self, ctx):  # pragma: no cover - never called here
            raise AssertionError

    plain = policy_digest(Policies())
    custom = policy_digest(Policies(acceptance=_MyAcceptance()))
    assert custom != plain


def test_merge_context_carries_the_digest_by_default_empty():
    assert "policy_digest" in MergeContext.__dataclass_fields__
    ctx = MergeContext(artifact=None, candidate=None, cards=[],
                       base_counts=(0.0, 1.0), cand_counts=(0.0, 1.0))
    assert ctx.policy_digest == ""      # additive: no digest, old behaviour


def test_the_commit_message_trailer_is_additive():
    d = _diff()
    assert merge_commit_message(d, "skill") == "merge w0:abc:1 -> skill"
    with_digest = merge_commit_message(d, "skill", policy_digest="c" * 64)
    assert with_digest.startswith("merge w0:abc:1 -> skill")
    assert "policy-digest: " + "c" * 64 in with_digest


def test_the_manifest_carries_the_digest_without_changing_manifest_id():
    spec = _spec()
    plain = build_manifest(spec)
    tagged = build_manifest(spec, policy_digest="d" * 64)
    assert tagged.policy_digest == "d" * 64
    assert tagged.to_dict()["policy_digest"] == "d" * 64
    assert tagged.manifest_id == plain.manifest_id   # the id describes the inputs


def test_a_manifest_and_record_written_before_the_field_still_load():
    old = {"manifest_id": "x", "spec_hash": "a", "data_hash": "b", "model_hash": "c",
           "code_version": "", "seeds": [], "algorithm": None, "files": {},
           "missing": [], "model_config": {}, "extra": {}}
    assert RunManifest.from_dict(old).policy_digest == ""
    old_record = {"record_id": "r1", "kind": "merge", "artifact_id": "skill",
                  "diff_id": "d", "accepted": True, "category": "committed",
                  "detail": "", "evidence": {}, "cost": {}, "parent_id": None,
                  "created_at": 1.0}
    assert DecisionRecord.from_dict(old_record).policy_digest == ""


def test_no_secret_material_enters_the_digest(tmp_path, monkeypatch):
    from agentdescent.policies import policy_digest

    monkeypatch.setenv("ARK_API_KEY", "sk-live-do-not-hash-this")
    digest = policy_digest(Policies(), config=AggregatorConfig())
    assert "do-not-hash" not in digest
    assert len(digest) == 64


# ---------------------------------------------------------------------------
# End to end: the engine stamps it, and it reaches the ledger
# ---------------------------------------------------------------------------


def _engine_run(**kw):
    from agentdescent import AppendRules, Task, evolve

    tasks = [Task(id=f"t{i}", prompt=f"q{i}", meta={"gold": str(i)})
             for i in range(6)]
    return evolve(tasks, lambda t, o: 1.0 if o == t.meta["gold"] else 0.0,
                  run=lambda r, t: t.meta["gold"] if t.id in r else "?",
                  propose=lambda r, t, o, s: t.id,
                  strategy=AppendRules(), rounds=3, n_workers=2,
                  held_out_frac=0.5, seed=0, **kw)


def test_an_evolve_run_stamps_its_policy_digest_on_the_ledger(tmp_path):
    """The point of the digest: read a commit, learn its procedure.

    A record only the record keeps is decoration -- this reads the actual git
    commit body the ledger wrote, which is where an auditor looks.
    """
    import subprocess

    repo = str(tmp_path / "ledger")
    result = _engine_run(repo_path=repo)
    assert len(result.policy_digest) == 64
    committed = sum(h.committed for h in result.history)
    assert committed, "the fixture run must commit, or this asserts nothing"
    body = subprocess.run(["git", "-C", repo, "log", "dev", "--format=%B"],
                          capture_output=True, text=True, check=True).stdout
    assert f"policy-digest: {result.policy_digest}" in body


def test_one_acceptance_knob_changes_the_version_and_nothing_else_does():
    """The acceptance criterion of #943, end to end and in both directions."""
    base = dict(batch_trigger=2, max_wait_rounds=1)
    tight = _engine_run(agg_config=AggregatorConfig(base_delta=0.05, **base))
    loose = _engine_run(agg_config=AggregatorConfig(base_delta=0.75, **base))
    assert tight.policy_digest != loose.policy_digest
    again = _engine_run(agg_config=AggregatorConfig(base_delta=0.05, **base))
    assert again.policy_digest == tight.policy_digest   # no clock, no ambient state
