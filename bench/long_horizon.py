#!/usr/bin/env python3
"""Long-horizon (continual) benchmark: one artifact, many steps, with lineage.

Every other bench in this repository measures one hop: a generation loop over a
fixed task set (``bench.rsi_bench``), or a chain of rungs run once
(``bench.self_evolution``). Recursive self-improvement is a **long** loop: the
same artifact is rewritten step after step, each step conditioned on the version
the previous step committed, and the thing that goes wrong at step 12 is usually
a decision that was locally correct at step 4. This bench measures that
directly -- one playbook, ``--steps`` sequential steps, a git ledger recording
which rewrites were committed and why the others were refused.

    python -m bench.long_horizon                   # human-readable, 9 steps, 3 seeds
    python -m bench.long_horizon --json            # machine-readable report
    python -m bench.long_horizon --steps 15 --json # the long end of the range

Why this domain
---------------
The artifact is a playbook ``SKILL.md`` of rule lines. A later line for the
same rule **overrides** the earlier one, so the playbook can carry a history
without being able to hold two answers to the same question. Six check families
read the rules, and they conflict by construction: ``add_sum`` and
``add_product`` want opposite bodies for the same rule, ``chain_add`` needs
``chain: add_then_mul`` *and* ``add: sum``, ``chain_mul`` needs
``chain: mul_then_add`` *and* ``mul: product``. No assignment of rule bodies
scores every check, so the loop cannot win outright -- it can only trade
families off. That is deliberate, and the JSON reports the reachable ceiling
beside the measured retention so a reader can see how much of the gap is the
loop's fault.

Each step is:

1. the next family in a seed-shuffled arrival order becomes the target;
2. a deterministic, offline proposer reads the playbook and emits the one rule
   line that fixes that family's checks -- no model call, no network;
3. the candidate is measured on the held-out checks;
4. :class:`~agentdescent.defaults.DefaultAcceptance` gates the rewrite and, when
   it passes, the :class:`~agentdescent.Ledger` commits it (content-addressed
   lineage); otherwise the step is recorded as refused and the artifact is left
   exactly as it was.

The gate reads the **held-out** checks only, and it never sees more than a third
of them. A rewrite that is free on the held-out set can still erase a family
that is passing, which is the failure mode this bench exists to measure. The
default holds out one check per family; lower ``--holdout-fraction`` and the
report names the families nothing is protecting (``families_without_holdout``)
instead of quietly measuring a split.

Metrics are each defined once, here, and nowhere else:

* ``retention`` -- the share of every check the final artifact passes;
* ``forgetting`` -- reused verbatim from :class:`~bench.rsi_bench.TaskCurve`
  (``max(0, max(valid) - valid[-1])``) per check, reported as a mean, a maximum
  and a fraction, exactly as :class:`~bench.rsi_bench.RSIBenchReport` does;
* ``transfer`` -- paired final-minus-step-0 on a fresh check set that no step
  ever measured, bootstrapped per seed with
  :func:`~agentdescent.stats_eval.bootstrap_ci`;
* ``cost`` -- check evaluations, wall clock, ledger commits and artifact bytes.

``--steps`` defaults to 9 and the published range is 5-15; anything from 1 to 15
is accepted so the test can exercise the same mechanics in three steps.

Seeds shuffle **which family arrives when** and nothing else; the held-out split
is by stable hash and is the same for every seed. Three seeds give a range, not
significance, and the report says so where the number is printed. Negative
results are published as they fall out: ``flat`` and ``regressing`` are verdicts,
not omissions.

Everything except ``cost.wall_clock_s`` is reproducible byte for byte; git commit
hashes never enter the report, because the lineage is identified by the content
hash of the playbook at each step instead.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import sys
import tempfile
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from agentdescent import (
    EvolvingArtifact,
    FileTree,
    Ledger,
    MergeContext,
    build_manifest,
)
from agentdescent.defaults import DefaultAcceptance
from agentdescent.filetree import canonical
from agentdescent.stats_eval import bootstrap_ci
from bench.rsi_bench import (
    BenchmarkTask,
    BenchStep,
    RSIBench,
    RSIBenchReport,
    TaskCurve,
)

__all__ = ["run_bench", "run_seed", "main", "check_tasks", "fresh_tasks"]

BENCH = "long_horizon"
VERSION = 1
PLAYBOOK = "SKILL.md"

#: The playbook's header. No ``- `` prefix, so it never parses as a rule.
HEADER = (
    "# Playbook\n"
    "Rules the loop edits. The last line for a rule is the one in force:\n"
    "earlier lines stay in the history and are never applied.\n"
)

#: ``family -> the (rule, body) pairs its checks need``. A check scores the
#: share of its pairs that are in force, so a chain check whose order is right
#: but whose dependency was rewritten away scores one half.
FAMILIES: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "add_sum": (("add", "sum"),),
    "add_product": (("add", "product"),),
    "mul_sum": (("mul", "sum"),),
    "mul_product": (("mul", "product"),),
    "chain_add": (("chain", "add_then_mul"), ("add", "sum")),
    "chain_mul": (("chain", "mul_then_add"), ("mul", "product")),
}
CHECKS_PER_FAMILY = 3
FRESH_PER_FAMILY = 2

#: Every assignment of rule bodies the playbook can express (last line wins, so
#: there is exactly one body in force per rule).
ASSIGNMENTS = tuple(
    dict(pairs)
    for pairs in itertools.product(
        (("add", "sum"), ("add", "product")),
        (("mul", "sum"), ("mul", "product")),
        (("chain", "add_then_mul"), ("chain", "mul_then_add")),
    )
)

#: A third of the checks: on the 18-check set this lands exactly one held-out
#: check per family, so the gate can see every family. The composition is
#: recomputed and reported (``checks.holdout_by_family``), never assumed -- a
#: gate that cannot see a family measures the split, not the loop, and
#: ``--holdout-fraction`` below this is what the forgetting test uses.
HOLDOUT_FRACTION = 1 / 3
GATE = dict(base_delta=0.5, anneal_half_life=64, accept_samples=4000)
MAX_STEPS = 15


# -- the artifact -------------------------------------------------------------


def parse_playbook(text: str) -> Dict[str, str]:
    """The rules in force: the **last** line for a rule wins."""
    effective: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("- ") or ":" not in line:
            continue
        rule, body = line[2:].split(":", 1)
        rule, body = rule.strip(), body.strip()
        if rule and body:
            effective[rule] = body
    return effective


def append_rule(text: str, rule: str, body: str) -> str:
    return f"{text.rstrip()}\n- {rule}: {body}\n"


def content_sha(state: Mapping[str, str]) -> str:
    """A short, stable id for exactly what the playbook says at one step."""
    return hashlib.sha256(canonical(state).encode("utf-8")).hexdigest()[:12]


def artifact_id(state: Mapping[str, str]) -> str:
    """``filetree.canonical(state)`` is the id, shortened to fit a filename.

    ``Ledger`` stores an artifact as ``artifacts/<id>.json``, so the canonical
    string (a JSON document) can only be used as an id through a digest of it.
    The full string is still what gets hashed -- no state is dropped.
    """
    return f"lh-{content_sha(state)[:10]}"


# -- the check set ------------------------------------------------------------


def check_tasks() -> Tuple[BenchmarkTask, ...]:
    """The 18 checks the loop is measured on (and mostly gated on)."""
    return tuple(
        BenchmarkTask(task_id=f"{family}-{i}", family=family,
                      payload={"requires": list(requires)})
        for family, requires in FAMILIES.items()
        for i in range(1, CHECKS_PER_FAMILY + 1)
    )


def fresh_tasks() -> Tuple[BenchmarkTask, ...]:
    """Checks no step ever measured: the transfer set.

    They ask the same questions as the loop's checks under different ids, so
    ``RSIBench.split`` would place them differently -- but they are used whole,
    as a before/after pair, and never enter the split.
    """
    return tuple(
        BenchmarkTask(task_id=f"fresh-{family}-{i}", family=family,
                      payload={"requires": list(requires)})
        for family, requires in FAMILIES.items()
        for i in range(1, FRESH_PER_FAMILY + 1)
    )


def check_score(task: BenchmarkTask, effective: Mapping[str, str]) -> float:
    requires = task.payload["requires"]
    matched = sum(1 for rule, body in requires if effective.get(rule) == body)
    return matched / len(requires)


def score_map(tasks: Sequence[BenchmarkTask],
              effective: Mapping[str, str]) -> Dict[str, float]:
    return {task.task_id: check_score(task, effective) for task in tasks}


def counts(tasks: Sequence[BenchmarkTask],
           effective: Mapping[str, str]) -> Tuple[float, float]:
    """``(successes, failures)`` over the tasks, with partial checks counted.

    A chain check scores one half when its order is right but a dependency was
    rewritten away, and a gate that only counts a check when it fully passes
    cannot see chain progress at all: the first ``chain`` rule moves the check
    from 0.0 to 0.5, never to 1.0, so the counts never move and the rule can
    never be committed (measured: every chain step refused, every run). The
    score *is* the measurement, so it is what the Beta posterior is fed;
    ``BetaPosterior`` takes float counts and refuses a non-finite one.
    """
    scores = [check_score(task, effective) for task in tasks]
    successes = sum(scores)
    return successes, len(scores) - successes


def reachable_ceiling(tasks: Sequence[BenchmarkTask]) -> float:
    """The best mean score any assignment of rule bodies reaches on this set.

    Without it a retention of 0.44 looks like a broken loop; beside it, the
    reader sees how much of the shortfall the conflicting families force.
    """
    return max(
        sum(check_score(task, assignment) for task in tasks) / len(tasks)
        for assignment in ASSIGNMENTS
    )


# -- the proposer -------------------------------------------------------------


def propose(family: str, effective: Mapping[str, str]) -> Tuple[str, str]:
    """The one rule line that fixes this family -- and only this family.

    A scripted stand-in for a reflector: it reads the playbook and the family it
    was pointed at, and returns the first requirement that is not in force. When
    the family already passes it re-proposes the line already in force, which is
    how a duplicate append reaches the gate instead of being filtered here.
    """
    requires = FAMILIES[family]
    for rule, body in requires:
        if effective.get(rule) != body:
            return rule, body
    return requires[0]


def arrival_order(seed: int) -> Tuple[str, ...]:
    """Which family arrives at which step. The **only** thing the seed changes."""
    order = list(FAMILIES)
    random.Random(seed).shuffle(order)
    return tuple(order)


# -- one seed -----------------------------------------------------------------


def _serializer(artifact: Any) -> Dict[str, str]:
    return dict(artifact.state)


def _deserializer(strategy: FileTree):
    def load(aid: str, version: int, state: Dict[str, str]) -> EvolvingArtifact:
        return EvolvingArtifact(aid, dict(state), version=version, strategy=strategy)

    return load


def _curve(task: BenchmarkTask, split: str, steps: Sequence[Mapping[str, float]],
           errors: Sequence[Optional[str]]) -> TaskCurve:
    return TaskCurve(
        task_id=task.task_id, family=task.family, split=split,
        scores=tuple(step[task.task_id] for step in steps),
        oracle=tuple(None for _ in steps),
        costs=tuple(0.0 for _ in steps),
        errors=tuple(errors),
    )


def run_seed(seed: int, *, steps: int = 9,
             holdout_fraction: float = HOLDOUT_FRACTION,
             workdir: Optional[str] = None,
             fail_step: Optional[int] = None) -> Dict[str, Any]:
    """One continual run: one artifact, ``steps`` sequential rewrites."""
    started = time.perf_counter()
    tasks = check_tasks()
    # The RSIBench instance is used for its hash split only; this loop's clock
    # is the step, not the generation, so `generations` is just the floor it
    # validates.
    bench = RSIBench(tasks, generations=max(2, steps),
                     holdout_fraction=holdout_fraction)
    train, holdout = bench.split()
    split_of = {task.task_id: "train" for task in train}
    split_of.update({task.task_id: "holdout" for task in holdout})
    holdout_set = tuple(holdout)

    tree = FileTree(initial_files={PLAYBOOK: HEADER}, max_files_per_diff=1)
    state = tree.initial()
    history = [score_map(tasks, parse_playbook(state[PLAYBOOK]))]
    errors: List[Optional[str]] = [None]
    evaluations = 0
    commits = 0
    order = arrival_order(seed)
    gate = DefaultAcceptance(**GATE)
    records: List[Dict[str, Any]] = []

    repo = tempfile.mkdtemp(prefix=f"long-horizon-{seed}-", dir=workdir)
    ledger = Ledger(repo, _serializer, _deserializer(tree))
    artifact = EvolvingArtifact(artifact_id(state), dict(state), strategy=tree)
    ledger.register(artifact)
    commits += 1  # the registration is the genesis node of the lineage

    def step(current: EvolvingArtifact, step_no: int, budget: float
             ) -> Tuple[EvolvingArtifact, BenchStep]:
        """One sequential rewrite, as ``(artifact, BenchStep)``; never a raise.

        The contract the issue asks for: the loop below is only a driver, so the
        step can be read, tested and swapped on its own. A failing step comes
        back as a ``BenchStep`` carrying the error, which is what lets a
        15-step run that breaks at step 12 still report eleven steps of
        evidence.
        """
        nonlocal state, evaluations, commits
        phase = order[(step_no - 1) % len(order)]
        effective = parse_playbook(state[PLAYBOOK])
        rule, body = propose(phase, effective)
        new_text = append_rule(state[PLAYBOOK], rule, body)
        candidate_state = dict(state)
        candidate_state[PLAYBOOK] = new_text
        proposal = json.dumps({
            "rationale": f"{phase} fails; set {rule}: {body}",
            "edits": [{"path": PLAYBOOK, "content": new_text}],
        })
        diff = tree.to_diff(state, proposal, "scripted-proposer",
                            current.version, current.id)
        record: Dict[str, Any] = {
            "step": step_no, "phase": phase, "rule": rule, "body": body,
            "budget": budget, "ok": True, "error": None, "committed": False,
            "parent_sha": content_sha(state), "child_sha": content_sha(state),
            "version_before": current.version, "version_after": current.version,
            "holdout_before": 0.0, "holdout_after": 0.0,
            "p_improve": 0.0, "gate": "", "reason": "",
        }
        updated = current
        try:
            if fail_step == step_no:
                raise RuntimeError(f"injected failure at step {step_no}")
            base_counts = counts(holdout_set, effective)
            candidate_effective = parse_playbook(new_text)
            cand_counts = counts(holdout_set, candidate_effective)
            candidate = EvolvingArtifact(current.id, candidate_state,
                                        version=current.version + 1,
                                        strategy=tree)
            before = MergeContext.rate(base_counts)
            after = MergeContext.rate(cand_counts)
            decision = gate.accept(MergeContext(
                artifact=current, candidate=candidate, cards=(),
                base_counts=base_counts, cand_counts=cand_counts, diff=diff))
            record.update({
                "holdout_before": before, "holdout_after": after,
                "p_improve": decision.p_improve,
                "gate": decision.category,
                "reason": decision.detail or decision.category,
            })
            if decision.accept:
                head = ledger.head_version()
                _, version = ledger.commit(
                    candidate, head,
                    message=(f"step {step_no}: {phase} -> {rule}: {body} "
                             f"(held-out {before:.2f} -> {after:.2f})"))
                commits += 1
                updated = EvolvingArtifact(current.id, candidate_state,
                                           version=version, strategy=tree)
                state = candidate_state
                record.update({
                    "committed": True, "child_sha": content_sha(state),
                    "version_after": version,
                })
        except Exception as exc:  # noqa: BLE001 - a failed step is a data point
            record.update({"ok": False, "gate": "raised",
                           "error": f"{type(exc).__name__}: {exc}",
                           "reason": "step raised; state left unchanged"})
        spent = 2 * len(holdout_set) + len(tasks)
        evaluations += spent
        step_scores = score_map(tasks, parse_playbook(state[PLAYBOOK]))
        history.append(step_scores)
        errors.append(record["error"])
        phase_score = _mean([step_scores[task.task_id] for task in tasks
                             if task.family == phase])
        record.update({"score": phase_score, "cost": float(spent)})
        records.append(record)
        return updated, BenchStep(score=phase_score, cost=float(spent),
                                  error=record["error"])

    step_budget = 1.0
    try:
        for step_no in range(1, steps + 1):
            artifact, _ = step(artifact, step_no, step_budget)
    finally:
        ledger.close()

    curves = tuple(_curve(task, split_of[task.task_id], history, errors)
                   for task in sorted(tasks, key=lambda item: item.task_id))
    train_curves = [c for c in curves if c.split == "train"]
    holdout_curves = [c for c in curves if c.split == "holdout"]
    train_gain = _mean([c.gain for c in train_curves])
    holdout_gain = _mean([c.gain for c in holdout_curves])
    forgetting = _mean([c.forgetting for c in curves])
    max_forgetting = max((c.forgetting for c in curves), default=0.0)
    forgetting_fraction = (
        sum(1 for c in curves if c.forgetting > 0.05) / len(curves) if curves else 0.0)
    error_count = sum(c.error_count for c in curves)
    final = parse_playbook(state[PLAYBOOK])
    final_scores = score_map(tasks, final)
    retention = _mean(list(final_scores.values()))

    fresh = fresh_tasks()
    before = score_map(fresh, parse_playbook(tree.initial()[PLAYBOOK]))
    after = score_map(fresh, final)
    evaluations += 2 * len(fresh)
    ci = bootstrap_ci(before, after, n=2000, seed=seed)

    if error_count:
        verdict = "errored"
    elif max_forgetting > 0.05:
        verdict = "forgetting"
    elif train_gain > 0.05 and ci.mean <= 1e-9:
        verdict = "no-transfer"
    elif ci.mean > 1e-9:
        verdict = "improving"
    elif ci.mean < -1e-9:
        verdict = "regressing"
    else:
        verdict = "flat"

    committed_now = sum(1 for record in records if record["committed"])
    report = RSIBenchReport(
        curves=curves, generations=len(history),
        train_gain=train_gain, holdout_gain=holdout_gain, transfer=ci.mean,
        forgetting=forgetting, max_forgetting=max_forgetting,
        forgetting_fraction=forgetting_fraction, reward_hacking_gap=None,
        cost=float(evaluations), generations_to_target=None, errors=error_count,
        verdict=verdict,
        detail=(f"{steps} step(s) over {len(tasks)} check(s), "
                f"{len(holdout_set)} held out, {committed_now} rewrite(s) "
                f"committed; retention={retention:.3f}, "
                f"max-forget={max_forgetting:.3f}, transfer={ci.mean:+.3f}"),
    )
    families_in_holdout = sorted({task.family for task in holdout_set})
    return {
        "seed": seed,
        "ok": error_count == 0,
        "verdict": verdict,
        "retention": retention,
        "ceiling": reachable_ceiling(tasks),
        "forgetting": forgetting,
        "max_forgetting": max_forgetting,
        "forgetting_fraction": forgetting_fraction,
        "committed": committed_now,
        "refused": sum(1 for record in records
                       if record["ok"] and not record["committed"]),
        "failed": sum(1 for record in records if not record["ok"]),
        "arrival_order": list(order),
        "transfer": {
            "mean": ci.mean, "lo": ci.lo, "hi": ci.hi,
            "prob_positive": ci.prob_positive, "pairs": ci.n,
            "definition": "paired final minus step-0 on the fresh check set, "
                          "bootstrapped over checks within this seed",
        },
        "families_without_holdout": [
            family for family in FAMILIES if family not in families_in_holdout],
        "cost": {
            "check_evaluations": evaluations,
            "ledger_commits": commits,
            "artifact_bytes": len(state[PLAYBOOK].encode("utf-8")),
            "artifact_lines": len(
                [line for line in state[PLAYBOOK].splitlines()
                 if line.startswith("- ")]),
            "wall_clock_s": round(time.perf_counter() - started, 3),
        },
        "final_rules": dict(sorted(final.items())),
        "steps": records,
        "lineage": [record for record in records if record["committed"]],
        "report": report.to_dict(),
    }


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# -- the whole run ------------------------------------------------------------


def run_bench(*, seeds: int = 3, steps: int = 9,
              holdout_fraction: float = HOLDOUT_FRACTION,
              workdir: Optional[str] = None,
              fail_step: Optional[int] = None,
              code_version: str = "") -> Dict[str, Any]:
    """Every seed, the manifest they share, and the spread across them."""
    if isinstance(steps, bool) or not isinstance(steps, int) \
            or not 1 <= steps <= MAX_STEPS:
        raise ValueError(f"steps must be an int in 1..{MAX_STEPS}")
    if isinstance(seeds, bool) or not isinstance(seeds, int) or seeds < 1:
        raise ValueError("seeds must be a positive int")

    seed_numbers = tuple(range(seeds))
    manifest = build_manifest(
        {
            "algorithm": {"name": "long-horizon-continual"},
            "evolve": {"seeds": list(seed_numbers)},
            "data": {"path": ""},
        },
        data_paths=[],
        model_config={"model": "none (offline scripted proposer)"},
        code_version=code_version,
        extra={
            "bench": BENCH, "steps": steps,
            "holdout_fraction": holdout_fraction,
            "proposer": "scripted-offline", "gate": "DefaultAcceptance",
        },
    )
    runs = [run_seed(seed, steps=steps, holdout_fraction=holdout_fraction,
                     workdir=workdir, fail_step=fail_step)
            for seed in seed_numbers]

    tasks = check_tasks()
    train, holdout = RSIBench(tasks, holdout_fraction=holdout_fraction).split()
    verdicts: Dict[str, int] = {}
    for run in runs:
        verdicts[run["verdict"]] = verdicts.get(run["verdict"], 0) + 1
    # Verdict order, weakest evidence first: a single seed that errored or lost a
    # family to forgetting outranks a seed that improved (#1177 review).
    for verdict in ("errored", "forgetting", "regressing", "no-transfer",
                    "flat", "improving"):
        if verdict in verdicts:
            overall = verdict
            break
    else:
        overall = "insufficient"

    return {
        "bench": BENCH,
        "version": VERSION,
        "manifest_id": manifest.manifest_id,
        "spec_hash": manifest.spec_hash,
        "code_version": manifest.code_version,
        "model": dict(manifest.model_config),
        "steps": steps,
        "seeds": list(seed_numbers),
        "checks": {
            "total": len(tasks),
            "train": len(train),
            "holdout": len(holdout),
            "holdout_ids": sorted(task.task_id for task in holdout),
            "holdout_by_family": {
                family: sum(1 for task in holdout if task.family == family)
                for family in FAMILIES
            },
            "families_without_holdout": [
                family for family in FAMILIES
                if not any(task.family == family for task in holdout)],
            "ceiling": reachable_ceiling(tasks),
        },
        "runs": runs,
        "summary": {
            "retention": {"min": min(r["retention"] for r in runs),
                          "max": max(r["retention"] for r in runs)},
            "forgetting": {"min": min(r["forgetting"] for r in runs),
                           "max": max(r["forgetting"] for r in runs)},
            "max_forgetting": max(r["max_forgetting"] for r in runs),
            "transfer": {
                "min": min(r["transfer"]["mean"] for r in runs),
                "max": max(r["transfer"]["mean"] for r in runs),
            },
            "committed": sum(r["committed"] for r in runs),
            "refused": sum(r["refused"] for r in runs),
            "failed": sum(r["failed"] for r in runs),
            "verdicts": verdicts,
        },
        "verdict": overall,
        "all_ok": all(run["ok"] for run in runs),
        "notes": [
            "three seeds are a range, not significance: each seed shuffles which "
            "family arrives when, and the report gives the min and max across them",
            f"the check families conflict by construction; the best assignment of "
            f"rule bodies reaches {reachable_ceiling(tasks):.3f} retention, so a "
            f"shortfall below that is the loop's, not the domain's",
            "the gate reads the held-out checks only; a family with no held-out "
            "check is not protected, which is what families_without_holdout names",
            "no proxy/oracle pair exists in this domain, so the verdict never says "
            "hacking and reward_hacking_gap is null",
        ],
    }


def _print_human(report: Mapping[str, Any]) -> None:
    checks = report["checks"]
    print(f"[{BENCH}] {report['steps']} step(s), {len(report['seeds'])} seed(s), "
          f"{checks['total']} check(s) ({checks['holdout']} held out), "
          f"ceiling {checks['ceiling']:.3f}")
    print(f"[{BENCH}] manifest {report['manifest_id'][:16]}  "
          f"model {report['model'].get('model', '?')}")
    for run in report["runs"]:
        status = "ok  " if run["ok"] else "FAIL"
        transfer = run["transfer"]
        print(
            f"  [{status}] seed {run['seed']}: retention {run['retention']:.3f}, "
            f"forgetting {run['forgetting']:.3f} (max {run['max_forgetting']:.3f}), "
            f"transfer {transfer['mean']:+.3f} "
            f"[{transfer['lo']:+.3f}, {transfer['hi']:+.3f}], "
            f"{run['committed']} committed / {run['refused']} refused / "
            f"{run['failed']} failed, verdict {run['verdict']}")
        for record in run["steps"]:
            mark = "commit " if record["committed"] else (
                "FAIL   " if not record["ok"] else "refuse ")
            print(f"          step {record['step']:>2} {record['phase']:<12} "
                  f"{mark} {record['rule']}: {record['body']}  {record['reason']}")
    print(f"[{BENCH}] verdict: {report['verdict']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    from agentdescent import __version__

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", type=int, default=9,
                        help=f"sequential rewrites of the one artifact "
                             f"(1..{MAX_STEPS}, default 9; published runs use "
                             f"5-15)")
    parser.add_argument("--seeds", type=int, default=3,
                        help="how many arrival orders to run (default 3)")
    parser.add_argument("--holdout-fraction", type=float,
                        default=HOLDOUT_FRACTION,
                        help="share of the checks the gate sees "
                             f"(default {HOLDOUT_FRACTION})")
    parser.add_argument("--json", action="store_true",
                        help="print only the machine-readable report")
    parser.add_argument("--out", default="",
                        help="also write the report to this path")
    parser.add_argument("--fail-step", type=int, default=None,
                        help="raise inside this step, to show a failed step is "
                             "recorded rather than crashing the run")
    parser.add_argument("--workdir", default=None,
                        help="parent for the temporary git ledgers")
    args = parser.parse_args(argv)
    if not 1 <= args.steps <= MAX_STEPS:
        parser.error(f"--steps must be in 1..{MAX_STEPS}")
    if args.seeds < 1:
        parser.error("--seeds must be >= 1")

    report = run_bench(seeds=args.seeds, steps=args.steps,
                       holdout_fraction=args.holdout_fraction,
                       workdir=args.workdir, fail_step=args.fail_step,
                       code_version=__version__)
    text = json.dumps(report, indent=2, ensure_ascii=False, default=str)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    if args.json:
        print(text)
    else:
        _print_human(report)
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
