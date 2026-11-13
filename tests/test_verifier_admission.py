"""A verifier's admission rate must be measured on both strata, not just the good one."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from agentdescent.admission import AdmissionReport
from agentdescent.policies import AcceptDecision, MergeContext
from agentdescent.promotion import (PromotionAction, PromotionRequest,
                                    PromotionRules, promote)
from agentdescent.verifier_curriculum import VerifierAgreement
from agentdescent.verifier_ensemble import EnsembleReport

ACCEPT = lambda ctx: AcceptDecision(True)
REJECT = lambda ctx: AcceptDecision(False, "inner-says-no")


def _ctx(base, cand):
    return MergeContext(artifact=SimpleNamespace(name=base),
                        candidate=SimpleNamespace(name=cand),
                        cards=[], base_counts=(0.5, 0.5), cand_counts=(0.9, 0.1))


def _gate(verifier, oracle, inner):
    score = lambda table: lambda artifact, task: table[artifact.name][task]
    return VerifierAgreement((0,), score(verifier), score(oracle),
                             sample_rate=1.0, rejected_sample_rate=1.0,
                             inner=inner)


# good: the oracle confirms the gain; flat: accepted, but no gain to confirm;
# bad: a regression the inner policy refuses before the verifier sees it.
VERIFIER = {"good-base": {0: 0.2}, "good-cand": {0: 0.9},
            "flat-base": {0: 0.5}, "flat-cand": {0: 0.5},
            "bad-base": {0: 0.9}, "bad-cand": {0: 0.2}}
ORACLE = {"good-base": {0: 0.2}, "good-cand": {0: 0.8},
          "flat-base": {0: 0.5}, "flat-cand": {0: 0.5},
          "bad-base": {0: 0.9}, "bad-cand": {0: 0.2}}


def _refuse_bad(ctx):
    return AcceptDecision(not ctx.artifact.name.startswith("bad"))


def test_a_report_states_both_strata_and_where_it_falls_short():
    clean = _gate(VERIFIER, ORACLE, lambda ctx: AcceptDecision(
        ctx.artifact.name.startswith("good")))
    for name in ("good", "flat", "bad"):
        clean.accept(_ctx(name + "-base", name + "-cand"))
    assert clean.admission_report().recommendation == "admit"

    gate = _gate(VERIFIER, ORACLE, _refuse_bad)
    outcomes = [gate.accept(_ctx(n + "-base", n + "-cand")).accept
                for n in ("good", "flat", "bad")]
    assert outcomes == [True, True, False]
    report = gate.admission_report()
    assert isinstance(report, AdmissionReport)
    assert (report.n_accepted, report.n_rejected) == (2, 1)
    assert report.precision == 0.5       # the flat commit's gain is not confirmed
    assert report.recall_bound == 1.0    # the rejected commit was a regression
    assert report.recommendation == "defer" and "precision" in report.reason


def test_rejected_good_work_is_demoted_and_an_unmeasured_stratum_defers():
    # The good commit, refused by the inner policy: good work thrown away.
    refusing = _gate({"base": {0: 0.2}, "cand": {0: 0.9}},
                     {"base": {0: 0.2}, "cand": {0: 0.8}}, REJECT)
    refusing.accept(_ctx("base", "cand"))
    report = refusing.admission_report()
    assert report.precision is None and report.recall_bound == 0.0
    assert report.recommendation == "reject" and "recall" in report.reason

    # Accepted only: the recall bound is unmeasured, so it defers, never passes.
    partial = _gate({"base": {0: 0.2}, "cand": {0: 0.9}},
                    {"base": {0: 0.2}, "cand": {0: 0.8}}, ACCEPT)
    assert partial.accept(_ctx("base", "cand")).accept
    report = partial.admission_report()
    assert report.precision == 1.0 and report.recall_bound is None
    assert report.recommendation == "defer" and "rejected" in report.reason


def _verifier(**overrides):
    values = dict(votes=(), score=0.9, passed=True, confidence=1.0,
                  disagreement=0.0, cost=0.0, stopped_early=False)
    values.update(overrides)
    return EnsembleReport(**values)


def _promote(admission, require=True):
    return promote(
        PromotionRequest(artifact_id="skill-1",
                         verifier=_verifier(admission=admission)),
        PromotionRules(require_eval=False, require_contamination=False,
                       require_risk=False, require_canary=False,
                       require_verifier_admission=require))


_DEMOTE = AdmissionReport(
    n_accepted=1, n_rejected=0, precision=1.0, recall_bound=0.0,
    recommendation="reject", reason="recall >= 0.000: rejects good work")


def test_promotion_defers_on_a_half_report_and_fails_closed_on_a_demote():
    for admission in (None, replace(_DEMOTE, recall_bound=None)):
        decision = _promote(admission)
        assert decision.action == PromotionAction.DEFER
        assert "admission" in " ".join(decision.missing + decision.reasons)
    decision = _promote(_DEMOTE)
    assert decision.action == PromotionAction.REJECT   # a demote is not a deferral
    assert "recall" in " ".join(decision.reasons)
    assert _promote(_DEMOTE, require=False).action == PromotionAction.PROMOTE
