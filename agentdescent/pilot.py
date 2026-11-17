"""One decision for one evolution run: promote, defer or reject (#937).

The engine has the pieces -- :func:`~agentdescent.evolution.evolve`,
:func:`~agentdescent.trust_evidence.build_trust_evidence`,
:func:`~agentdescent.promotion.promote`, :class:`~agentdescent.manifest.RunManifest`
-- but a user still has to wire them in the right order and read five outputs.
Pilot is that last mile and **not** a new optimizer: it runs one evolution,
scores the seed and the result on the *same disjoint test tasks*, turns the
paired scores into evidence, and asks :func:`promote` for one verdict.

    report = pilot(PilotPolicy(
        tasks=train, test_tasks=test, reward=reward,
        run=run, propose=propose, strategy=AppendRules(),
    ), PilotConfig(artifact_id="skill", contaminated=False))
    report.action          # promote | defer | reject
    report.to_markdown()   # the human artifact

Honesty rules live here because this is where a caller could otherwise be
tempted to round a run up:

* a test task that raised is **not** scored as zero; it is run-health evidence,
  and a run above ``max_failure_rate`` cannot promote;
* a byte-identical artifact reports ``noise_only`` and a zero gain;
* a missing contamination check defers, a contaminated dataset rejects before
  any model call;
* the test split must be disjoint from the evolve pool by task id. Overlap is
  refused before spending, not discovered in the report;
* a multi-seed run never reports one seed's artifact next to scores pooled
  across every seed. A single artifact is reported only when every seed
  produced it; otherwise the report summarizes per seed and the pooled
  scores describe the method, not one candidate.

The module does not apply anything. ``apply``/release stays an explicit,
separate step.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .agents import Usage
from .evolution import Task, evolve
from .manifest import RunManifest, build_manifest
from .promotion import (PromotionAction, PromotionDecision, PromotionRequest,
                        PromotionRules, promote)
from .trust_evidence import RunHealth, TrustEvidence, build_trust_evidence

__all__ = ["PilotConfig", "PilotPolicy", "PilotReport", "pilot", "pilot_scores"]

SCHEMA_VERSION = 1


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not bool")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _task_id(task: Any) -> str:
    value = getattr(task, "id", None)
    if value is None and isinstance(task, Mapping):
        value = task.get("id")
    if value is None:
        raise ValueError("every pilot task needs an id")
    return str(value)


def _ids(tasks: Sequence[Any], name: str) -> Tuple[str, ...]:
    if isinstance(tasks, (str, bytes)) or not isinstance(tasks, Sequence):
        raise TypeError(f"{name} must be a sequence")
    ids = tuple(_task_id(task) for task in tasks)
    if not ids:
        raise ValueError(f"{name} must not be empty")
    if len(set(ids)) != len(ids):
        raise ValueError(f"{name} has duplicate task ids")
    return ids


def _fingerprint(tasks: Sequence[Any]) -> str:
    body = json.dumps(
        [{"id": _task_id(task), "prompt": getattr(task, "prompt", ""),
          "meta": getattr(task, "meta", {}) or {}}
         for task in tasks],
        sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


@dataclass(frozen=True)
class PilotConfig:
    """The knobs one pilot run may set; everything else is the engine's default."""

    artifact_id: str = "artifact"
    rounds: int = 8
    n_workers: int = 4
    max_concurrency: int = 4
    held_out_frac: float = 0.4
    seeds: Tuple[int, ...] = (0,)
    asynchronous: bool = False
    async_ratio: int = 3
    contaminated: Optional[bool] = None
    risk: Optional[float] = 0.2
    alpha: float = 0.05
    min_effect: float = 0.0
    max_failure_rate: float = 0.2
    rules: Optional[PromotionRules] = None
    dry_run: bool = False
    budget: Optional[Mapping[str, Any]] = None
    model_config: Mapping[str, Any] = field(default_factory=dict)
    data_paths: Tuple[str, ...] = ()
    code_version: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty string")
        for name in ("rounds", "n_workers", "max_concurrency"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be an int of at least 1")
        held = _finite(self.held_out_frac, "held_out_frac")
        if not 0.0 < held < 1.0:
            raise ValueError("held_out_frac must be in (0, 1)")
        seeds = tuple(self.seeds)
        if not seeds or any(isinstance(s, bool) or not isinstance(s, int)
                            for s in seeds):
            raise ValueError("seeds must be a non-empty tuple of ints")
        if len(set(seeds)) != len(seeds):
            raise ValueError("seeds must not repeat")
        if self.contaminated is not None and not isinstance(
                self.contaminated, bool):
            raise TypeError("contaminated must be a bool or None")
        if self.risk is not None:
            risk = _finite(self.risk, "risk")
            if not 0.0 <= risk <= 1.0:
                raise ValueError("risk must be in [0, 1]")
        alpha = _finite(self.alpha, "alpha")
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha must be in (0, 1)")
        if _finite(self.min_effect, "min_effect") < 0:
            raise ValueError("min_effect must be >= 0")
        threshold = _finite(self.max_failure_rate, "max_failure_rate")
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("max_failure_rate must be in [0, 1]")
        if self.rules is not None and not isinstance(self.rules, PromotionRules):
            raise TypeError("rules must be a PromotionRules or None")
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run must be a bool")
        if not isinstance(self.asynchronous, bool):
            raise TypeError("asynchronous must be a bool")
        if isinstance(self.async_ratio, bool) or not isinstance(
                self.async_ratio, int) or self.async_ratio < 1:
            raise ValueError("async_ratio must be an int of at least 1")
        if self.budget is not None:
            if not isinstance(self.budget, Mapping):
                raise TypeError("budget must be a mapping or None")
            unknown = set(self.budget) - {
                "max_calls", "max_tokens", "max_rollouts", "max_seconds"}
            if unknown:
                raise ValueError(
                    f"unknown budget key(s): {', '.join(sorted(unknown))}")
        object.__setattr__(self, "seeds", seeds)
        object.__setattr__(self, "model_config",
                           dict(self.model_config or {}))
        object.__setattr__(self, "data_paths",
                           tuple(str(path) for path in self.data_paths or ()))
        object.__setattr__(self, "extra", dict(self.extra or {}))


@dataclass(frozen=True)
class PilotPolicy:
    """What pilot runs: one artifact, two disjoint task sets, one scorer.

    ``agent=`` and ``run``/``propose`` are two spellings of the same actor; pass
    one. ``test_tasks`` is the only split the report measures, and it must not
    overlap ``tasks`` -- the engine's held-out split decides what commits, and
    reusing it here would leak selection into the number a reader trusts.
    """

    tasks: Sequence[Task]
    test_tasks: Sequence[Task]
    reward: Callable[[Task, str], float]
    strategy: Any
    run: Optional[Callable[[str, Task], str]] = None
    propose: Optional[Callable[[str, Task, str, float], Optional[str]]] = None
    agent: Optional[Any] = None
    initial_state: Optional[Mapping[str, str]] = None
    artifact_id: str = "artifact"
    usage: Optional[Usage] = None

    def __post_init__(self) -> None:
        _ids(self.tasks, "tasks")
        _ids(self.test_tasks, "test_tasks")
        if not callable(self.reward):
            raise TypeError("reward must be callable")
        if self.strategy is None:
            raise TypeError("strategy is required")
        for name in ("render", "initial"):
            if not callable(getattr(self.strategy, name, None)):
                raise TypeError(f"strategy needs a {name}() method")
        if self.agent is None:
            if not callable(self.run) or not callable(self.propose):
                raise TypeError("pass run= and propose=, or agent=")
        else:
            for name in ("solve", "propose"):
                if not callable(getattr(self.agent, name, None)):
                    raise TypeError(f"agent needs a {name}() method")
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("artifact_id must be a non-empty string")
        if self.initial_state is not None:
            object.__setattr__(self, "initial_state", dict(self.initial_state))

    @property
    def scorer(self) -> Callable[[str, Task], str]:
        return self.agent.solve if self.agent is not None else self.run


@dataclass(frozen=True)
class PilotReport:
    """One schema-versioned report: the decision, its evidence and what to do next."""

    artifact_id: str
    status: str
    decision: Optional[PromotionDecision] = None
    before: Mapping[str, float] = field(default_factory=dict)
    after: Mapping[str, float] = field(default_factory=dict)
    evidence: Optional[TrustEvidence] = None
    manifest: Optional[RunManifest] = None
    run: Mapping[str, Any] = field(default_factory=dict)
    cost: Mapping[str, Any] = field(default_factory=dict)
    next: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    error: Optional[str] = None
    #: The interval level the evidence was built with. Kept on the report so
    #: the Markdown card can say 95% or 90% without re-parsing a detail string.
    alpha: float = 0.05

    @property
    def action(self) -> Optional[str]:
        return None if self.decision is None else self.decision.action

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "artifact_id": self.artifact_id,
            "status": self.status,
            "decision": (None if self.decision is None
                         else self.decision.to_dict()),
            "run": dict(self.run),
            "before": dict(self.before),
            "after": dict(self.after),
            "evidence": (None if self.evidence is None
                         else self.evidence.to_dict()),
            "manifest": (None if self.manifest is None
                         else self.manifest.to_dict()),
            "cost": dict(self.cost),
            "next": list(self.next),
            "notes": list(self.notes),
            "error": self.error,
        }

    def to_markdown(self) -> str:
        """A stable, readable card -- scores, hashes and counts only."""
        action = (self.action or self.status).upper()
        lines = [f"# Pilot: {self.artifact_id}", "", f"Decision: **{action}**"]
        if self.decision is not None and self.decision.reasons:
            lines.append("")
            lines.extend(f"- {reason}" for reason in self.decision.reasons)
        if self.evidence is not None:
            result = self.evidence.eval_result
            lo, hi = result.ci
            lines += [
                "",
                f"Test: n={result.n}  baseline {result.baseline:.3f} -> "
                f"final {result.score:.3f}  (gain {self.evidence.gain:+.3f}, "
                f"{int((1 - self.alpha) * 100)}% CI "
                f"{lo:+.3f}..{hi:+.3f})",
            ]
            if self.evidence.run_health is not None:
                health = self.evidence.run_health
                lines.append(
                    f"Run health: {health.failed}/{health.attempted} failed "
                    f"(rate {health.failure_rate:.2f}, threshold "
                    f"{health.threshold:.2f})")
            if self.evidence.noise_only:
                lines.append("Artifact unchanged: the moved score is noise, not "
                             "learning")
        if self.cost:
            lines.append(
                f"Cost: {self.cost.get('calls', 0)} calls, "
                f"{self.cost.get('total_tokens', 0)} tokens, "
                f"{self.cost.get('seconds', 0.0):.1f}s")
        if self.manifest is not None:
            lines.append(f"Manifest: {self.manifest.manifest_id[:16]}")
        if self.next:
            lines += ["", "Next:"]
            lines.extend(f"- {item}" for item in self.next)
        if self.notes:
            lines += ["", "Notes:"]
            lines.extend(f"- {note}" for note in self.notes)
        if self.error:
            lines += ["", f"Error: {self.error}"]
        return "\n".join(lines) + "\n"


def _score(run: Callable[[str, Task], str],
           reward: Callable[[Task, str], float],
           rendered: str, tasks: Sequence[Task]) -> Tuple[Dict[str, float],
                                                          Tuple[str, ...]]:
    """Score every task; a task that raised is a failure, never a zero."""
    scores: Dict[str, float] = {}
    failed = []
    for task in tasks:
        task_id = _task_id(task)
        try:
            output = run(rendered, task)
            value = reward(task, output)
            value = _finite(value, f"reward for {task_id!r}")
        except Exception:  # noqa: BLE001 - a provider/harness failure
            failed.append(task_id)
            continue
        scores[task_id] = value
    return scores, tuple(failed)


def _initial_rendered(policy: PilotPolicy) -> str:
    state = (policy.strategy.initial() if policy.initial_state is None
             else dict(policy.initial_state))
    return policy.strategy.render(state)


def _manifest(policy: PilotPolicy, config: PilotConfig) -> RunManifest:
    spec = {
        "artifact_id": policy.artifact_id or config.artifact_id,
        "evolve": {
            "seeds": list(config.seeds),
            "rounds": config.rounds,
            "n_workers": config.n_workers,
            "max_concurrency": config.max_concurrency,
            "held_out_frac": config.held_out_frac,
        },
        "data": {"tasks": len(policy.tasks),
                 "test_tasks": len(policy.test_tasks)},
    }
    extra = dict(config.extra)
    extra.setdefault("evolve_fingerprint", _fingerprint(policy.tasks))
    extra.setdefault("test_fingerprint", _fingerprint(policy.test_tasks))
    return build_manifest(
        spec, data_paths=config.data_paths,
        model_config=config.model_config, code_version=config.code_version,
        extra=extra)


def _rules(config: PilotConfig) -> PromotionRules:
    return config.rules or PromotionRules()


def _decide(evidence: TrustEvidence, artifact_id: str, config: PilotConfig,
            *, artifact_hash: Optional[str] = None
            ) -> Tuple[TrustEvidence, PromotionDecision]:
    """Ask ``promote`` without letting an optional report veto the decision.

    ``build_trust_evidence`` always computes conformal and sequential reports.
    A ``continue``/``insufficient`` is not a rejection of the artifact; it means
    that test has not decided. The release surfaces already drop those two when
    the rules do not require them, and pilot must follow the same rule or every
    short run would defer on a check the caller never asked for.
    """
    rules = _rules(config)
    if (not rules.require_conformal and evidence.conformal is not None
            and evidence.conformal.decision == "insufficient"):
        evidence = replace(evidence, conformal=None)
    if (not rules.require_sequential and evidence.sequential is not None
            and evidence.sequential.decision == "continue"):
        evidence = replace(evidence, sequential=None)
    decision = promote(
        evidence.to_promotion_request(artifact_id, artifact_hash=artifact_hash),
        rules)
    return evidence, decision


def _defer_without_eval(artifact_id: str, *, config: PilotConfig,
                        reason: str) -> PromotionDecision:
    """A legitimate ``defer`` when the measurement cannot be evidence.

    ``promote`` decides from evidence; a run that died or measured nothing has
    none, so the request carries the two facts it does have (contamination and
    risk) and ``require_eval`` turns the absence into ``defer`` rather than a
    manufactured rejection.
    """
    request = PromotionRequest(
        artifact_id=artifact_id, contaminated=config.contaminated,
        risk=config.risk, metadata={"pilot": reason})
    return promote(request, _rules(config))


def _cost(usage: Usage) -> Dict[str, Any]:
    return {"calls": usage.calls, "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens, "seconds": usage.seconds,
            "failures": usage.failures}


def _next_actions(decision: Optional[PromotionDecision], *,
                  artifacts_agree: Optional[bool] = None) -> Tuple[str, ...]:
    if decision is None:
        return ("fix the report's error and rerun",)
    if decision.action == PromotionAction.PROMOTE:
        if artifacts_agree is False:
            # The report names no artifact, so the steps must not name one
            # either (#1141): point at the per-seed rows it does publish.
            return ("pick one seed's artifact from `run.per_seed` and review "
                    "that diff",
                    "apply the chosen artifact as a separate, explicit step",
                    "keep the manifest and this report for audit")
        return ("review the artifact diff", "apply it as a separate, explicit step",
                "keep the manifest and this report for audit")
    if decision.action == PromotionAction.DEFER:
        missing = ", ".join(decision.missing) or "more evidence"
        return (f"supply the missing evidence: {missing}",
                "rerun with more seeds or a cleaner run before shipping")
    if decision.action == PromotionAction.ROLLBACK:
        return ("roll the artifact back", "inspect the canary's reason")
    return ("do not ship this change", "keep the run for the next proposal")


def _artifact_hash(rendered: str) -> str:
    return hashlib.sha256(rendered.encode()).hexdigest()


def _shared_artifact(
        per_seed: Sequence[Mapping[str, Any]],
) -> Optional[Tuple[int, str]]:
    """Return ``(index, hash)`` only when every produced artifact agrees.

    Seeds that never recorded an artifact hash are skipped. If two hashes
    differ, return ``None`` so pooled scores cannot be pinned on one seed.
    """
    seen: list[Tuple[int, str]] = []
    for index, row in enumerate(per_seed):
        digest = row.get("artifact_hash")
        if not digest:
            continue
        seen.append((index, str(digest)))
    if not seen:
        return None
    first = seen[0][1]
    if any(digest != first for _, digest in seen):
        return None
    return seen[0][0], first


def _notes(config: PilotConfig, evidence: Optional[TrustEvidence],
           *, reported_seed: Optional[int] = None,
           artifacts_agree: Optional[bool] = None) -> Tuple[str, ...]:
    notes = []
    if len(config.seeds) == 1:
        notes.append("one seed; rerun with at least two before quoting the "
                     "magnitude")
    else:
        notes.append("seeds reuse the same test tasks; the interval is a paired "
                     "bootstrap over seed-task pairs, not a cluster-robust one")
        if artifacts_agree is False:
            notes.append("seeds produced different artifacts; the pooled scores "
                         "describe the method, not a single artifact")
        elif artifacts_agree is True and reported_seed is not None:
            notes.append(
                f"every seed produced the same artifact (seed {reported_seed}); "
                "the scores pool every seed")
    notes.append("token counts are real only when the model adapter shares "
                 "the run's Usage")
    if config.contaminated is None:
        notes.append("contamination was not checked")
    if evidence is not None:
        if evidence.noise_only:
            notes.append("the artifact is byte-identical before and after")
        if evidence.run_health is not None and evidence.run_health.censored:
            notes.append("run health is above the failure threshold; the "
                         "measurement is censored")
    return tuple(notes)


def pilot_scores(
        before: Mapping[str, float], after: Mapping[str, float], *,
        config: Optional[PilotConfig] = None, artifact_id: Optional[str] = None,
        artifact_changed: Optional[bool] = None,
        run_health: Optional[RunHealth] = None,
        manifest: Optional[RunManifest] = None,
        run: Optional[Mapping[str, Any]] = None,
        cost: Optional[Mapping[str, Any]] = None,
        notes: Sequence[str] = (),
) -> PilotReport:
    """The decision half of pilot: paired scores in, one report out.

    Use this when the evolution already happened somewhere else and only the
    decision/report seam is missing. :func:`pilot` calls it after it has scored
    the test split itself.
    """
    config = config or PilotConfig()
    artifact_id = artifact_id or config.artifact_id
    evidence = build_trust_evidence(
        before, after, contaminated=config.contaminated, risk=config.risk,
        artifact_changed=artifact_changed, alpha=config.alpha,
        min_effect=config.min_effect)
    if run_health is not None:
        # ``build_trust_evidence`` predates the field; ``TrustEvidence`` is the
        # construction point that drops failed tasks, so attach it there.
        evidence = replace(evidence, run_health=run_health)
    evidence, decision = _decide(evidence, artifact_id, config)
    return PilotReport(
        artifact_id=artifact_id, status="decided", decision=decision,
        before=dict(before), after=dict(after), evidence=evidence,
        manifest=manifest, run=dict(run or {}), cost=dict(cost or {}),
        next=_next_actions(decision),
        notes=tuple(notes) + _notes(config, evidence), alpha=config.alpha)


def pilot(policy: PilotPolicy,
          config: Optional[PilotConfig] = None) -> PilotReport:
    """Run one evolution and return one trustworthy decision (#937).

    The seed and the result are scored on the **same** disjoint test tasks; the
    engine's held-out split is never reused for the number the report quotes.
    Nothing is applied, merged or pushed.
    """
    config = config or PilotConfig()
    artifact_id = policy.artifact_id or config.artifact_id
    manifest = _manifest(policy, config)

    train_ids = set(_ids(policy.tasks, "tasks"))
    test_ids = _ids(policy.test_tasks, "test_tasks")
    overlap = sorted(train_ids & set(test_ids))
    if overlap:
        return PilotReport(
            artifact_id=artifact_id, status="refused", manifest=manifest,
            run={"test_tasks": len(test_ids), "tasks": len(train_ids)},
            next=("move the overlapping tasks into the evolve pool or the test "
                  "split, never both",),
            error=(f"test split overlaps the evolve pool on {len(overlap)} "
                   f"task(s): {', '.join(overlap[:5])}"),
            notes=("refused before any model call",))

    if config.dry_run:
        return PilotReport(
            artifact_id=artifact_id, status="planned", manifest=manifest,
            run={"tasks": len(train_ids), "test_tasks": len(test_ids),
                 "seeds": list(config.seeds), "rounds": config.rounds,
                 "n_workers": config.n_workers,
                 "budget": dict(config.budget or {})},
            next=("rerun without --dry-run to spend the quoted budget",),
            notes=("dry run: no model call was made",))

    if config.contaminated is True:
        # Refuse before spending: a contaminated dataset cannot yield a
        # defensible gain, so paying for the run only buys a bigger report.
        decision = promote(
            PromotionRequest(artifact_id=artifact_id, contaminated=True,
                             risk=config.risk, metadata={"pilot": "preflight"}),
            _rules(config))
        return PilotReport(
            artifact_id=artifact_id, status="refused", decision=decision,
            manifest=manifest,
            notes=("refused before any model call: the dataset is contaminated",),
            next=_next_actions(decision))

    run = policy.scorer
    usage = policy.usage if policy.usage is not None else Usage()
    initial = _initial_rendered(policy)
    before, baseline_failures = _score(run, policy.reward, initial,
                                       policy.test_tasks)

    before_all: Dict[str, float] = {}
    after_all: Dict[str, float] = {}
    failed_all: list[str] = []
    per_seed = []
    results = []
    errors = []
    for seed in config.seeds:
        failed_all.extend(f"{seed}:{task}" for task in baseline_failures)
        kwargs: Dict[str, Any] = {}
        budget = dict(config.budget or {})
        for key in ("max_calls", "max_tokens", "max_rollouts", "max_seconds"):
            if budget.get(key) is not None:
                kwargs[key] = budget[key]
        if policy.agent is not None:
            result = evolve(policy.tasks, policy.reward, agent=policy.agent,
                            strategy=policy.strategy,
                            initial_state=policy.initial_state,
                            rounds=config.rounds, n_workers=config.n_workers,
                            max_concurrency=config.max_concurrency,
                            held_out_frac=config.held_out_frac, seed=seed,
                            asynchronous=config.asynchronous,
                            async_ratio=config.async_ratio, usage=usage,
                            **kwargs)
        else:
            result = evolve(policy.tasks, policy.reward, run=policy.run,
                            propose=policy.propose,
                            strategy=policy.strategy,
                            initial_state=policy.initial_state,
                            rounds=config.rounds, n_workers=config.n_workers,
                            max_concurrency=config.max_concurrency,
                            held_out_frac=config.held_out_frac, seed=seed,
                            asynchronous=config.asynchronous,
                            async_ratio=config.async_ratio, usage=usage,
                            **kwargs)
        if result.error:
            errors.append(f"seed {seed}: {result.error}")
        after, failed = _score(run, policy.reward, result.rendered,
                               policy.test_tasks)
        for task in policy.test_tasks:
            task_id = _task_id(task)
            key = f"{seed}:{task_id}"
            if task_id in before and task_id in after:
                before_all[key] = before[task_id]
                after_all[key] = after[task_id]
        failed_all.extend(f"{seed}:{task}" for task in failed)
        common = [task_id for task_id in after if task_id in before]
        per_seed.append({
            "seed": seed, "accepted": result.outcomes().get("committed", 0),
            "outcomes": dict(result.outcomes()),
            "stop_reason": result.stop_reason, "error": result.error,
            "initial_reward": result.initial_reward,
            "final_reward": result.final_reward,
            "test_gain": ((sum(after[t] - before[t] for t in common) /
                           len(common)) if common else None),
            "artifact_hash": _artifact_hash(result.rendered),
        })
        results.append(result)

    shared = _shared_artifact(per_seed)
    if shared is not None:
        chosen = results[shared[0]]
        artifact_hash = shared[1]
        reported_seed = per_seed[shared[0]]["seed"]
        artifacts_agree = True
        artifact_changed = initial != chosen.rendered
        run_report = {
            "rounds": config.rounds, "n_workers": config.n_workers,
            "seeds": list(config.seeds), "stop_reason": chosen.stop_reason,
            "error": chosen.error,
            "accepted": chosen.outcomes().get("committed", 0),
            "outcomes": dict(chosen.outcomes()), "per_seed": per_seed,
            "initial_reward": chosen.initial_reward,
            "final_reward": chosen.final_reward,
            "reported_seed": reported_seed, "artifact_hash": artifact_hash,
            "artifacts_agree": True,
        }
    else:
        chosen = None
        artifact_hash = None
        reported_seed = None
        artifacts_agree = False
        artifact_changed = any(initial != result.rendered for result in results)
        run_report = {
            "rounds": config.rounds, "n_workers": config.n_workers,
            "seeds": list(config.seeds), "stop_reason": None, "error": None,
            "accepted": None, "outcomes": {}, "per_seed": per_seed,
            "initial_reward": None, "final_reward": None,
            "reported_seed": None, "artifact_hash": None,
            "artifacts_agree": False,
        }
    cost = _cost(usage)
    notes = _notes(config, None, reported_seed=reported_seed,
                   artifacts_agree=artifacts_agree)

    failed_all = list(dict.fromkeys(failed_all))
    if errors or not before_all or not after_all:
        reason = (errors[0] if errors else
                  "no test task produced a score on both sides")
        decision = _defer_without_eval(artifact_id, config=config, reason=reason)
        return PilotReport(
            artifact_id=artifact_id, status="error", decision=decision,
            before=before_all, after=after_all, manifest=manifest,
            run=run_report, cost=cost,
            next=_next_actions(decision, artifacts_agree=artifacts_agree),
            notes=notes, alpha=config.alpha, error=reason)

    health = RunHealth(
        attempted=len(policy.test_tasks) * len(config.seeds),
        failed_tasks=tuple(failed_all),
        threshold=config.max_failure_rate)
    evidence = build_trust_evidence(
        before_all, after_all, contaminated=config.contaminated,
        risk=config.risk, artifact_changed=artifact_changed,
        alpha=config.alpha, min_effect=config.min_effect)
    evidence = replace(evidence, run_health=health)
    evidence, decision = _decide(evidence, artifact_id, config,
                                 artifact_hash=artifact_hash)
    return PilotReport(
        artifact_id=artifact_id, status="decided", decision=decision,
        before=before_all, after=after_all, evidence=evidence, manifest=manifest,
        run=run_report, cost=cost,
        next=_next_actions(decision, artifacts_agree=artifacts_agree),
        notes=_notes(config, evidence, reported_seed=reported_seed,
                     artifacts_agree=artifacts_agree), alpha=config.alpha)
