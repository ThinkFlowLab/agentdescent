# Long-horizon bench — one artifact, nine steps, with lineage

*Script:* [`bench/long_horizon.py`](https://github.com/ThinkFlowLab/agentdescent/blob/main/bench/long_horizon.py)

Every other bench here measures one hop: a generation loop over a fixed task
set (`bench.rsi_bench`), or each rung of the meta stack run once
(`bench.self_evolution`). Recursive self-improvement is a long loop — the same
artifact rewritten step after step, each step conditioned on the version the
previous one committed — and the usual failure is a decision that was locally
correct at step 4 and wrong at step 12. This bench evolves **one** playbook
across sequential steps on a git ledger, and publishes the refusals as well as
the commits.

```bash
python -m bench.long_horizon                        # 9 steps × 3 seeds, human-readable
python -m bench.long_horizon --json                 # machine-readable report
python -m bench.long_horizon --steps 9 --seeds 3 \
    --out bench/results/long-horizon-3seed.json     # the committed results
```

It is offline, deterministic and needs no model key. It exits `0` only when
every step was recorded `ok`.

## The domain

The artifact is a playbook `SKILL.md` of rule lines. **A later line for the
same rule overrides the earlier one**, so the playbook keeps its history
without being able to hold two answers to the same question — which is what
makes a rewrite able to destroy a skill that was passing. Six check families
read the rules, and they conflict by construction:

| Family | Checks need | Conflicts with |
| --- | --- | --- |
| `add_sum` | `add: sum` | `add_product` |
| `add_product` | `add: product` | `add_sum`, `chain_add` |
| `mul_sum` | `mul: sum` | `mul_product`, `chain_mul` |
| `mul_product` | `mul: product` | `mul_sum` |
| `chain_add` | `chain: add_then_mul` **and** `add: sum` | `chain_mul`, `add_product` |
| `chain_mul` | `chain: mul_then_add` **and** `mul: product` | `chain_add`, `mul_sum` |

A chain check scores the share of its two requirements that are in force, so a
chain whose order is right but whose dependency was rewritten away scores one
half. Three checks per family, eighteen in all. No assignment of rule bodies
satisfies every check: the best one reaches **0.583**, and the report prints
that ceiling beside the measured retention so a shortfall can be attributed.

## One step

1. The next family in the **seed-shuffled arrival order** becomes the target.
2. A deterministic, offline proposer reads the playbook and emits the single
   rule line that fixes that family — no model call. It sees only its target
   family.
3. The candidate goes through `FileTree.to_diff`, so the tree's own size and
   path guards apply and the diff id is content-fingerprinted.
4. `DefaultAcceptance` gates the rewrite on the **held-out** checks.
5. Accepted → `Ledger.commit`, with the rewrite in the message; refused → the
   step is recorded with the gate's own reason and the artifact is untouched.

Lineage is the chain of committed states. Each step records the content sha of
the playbook before and after it, so the lineage is verifiable without
depending on a git hash — git commit hashes never enter the report.

## What it measured

Nine steps, three seeds (`bench/results/long-horizon-3seed.json`, manifest
`455feebf…`):

| Seed | Retention | Forgetting (max) | Transfer, 95% CI | Committed / refused | Verdict |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.583 | 0.333 (1.000) | +0.583 [+0.333, +0.833] | 5 / 4 | `forgetting` |
| 1 | 0.583 | 0.167 (1.000) | +0.583 [+0.333, +0.833] | 4 / 5 | `forgetting` |
| 2 | 0.583 | 0.333 (1.000) | +0.583 [+0.333, +0.833] | 5 / 4 | `forgetting` |

Every seed ends on the best reachable assignment (retention 0.583 = the
ceiling), and every seed is still a `forgetting` result: two families, three
checks each, were passing earlier in the run and are gone at the end. Seed 0
sets `add: product` at step 3 and takes it back at step 4; `mul: sum` from step
2 does not survive `mul: product` at step 6. Aggregate retention hides that
completely — which is why forgetting is reported per check, with a mean, a
maximum and a fraction, exactly as `RSIBenchReport` reports it.

The other half of the story is in the refusals: 13 of 27 steps were refused.
Seed 0 step 8 re-proposes `mul: sum` and the gate answers
`held-out regression 0.583 -> 0.500`; seed 1 step 5 proposes `chain:
add_then_mul`, which completes `chain_add` but breaks `chain_mul` by the same
half-check, so the posterior lands on `P(delta>0)=0.50` and refuses. On this
domain the gate is what stops the churn from being worse than it is.

Three seeds are a **range, not significance**: each seed only shuffles which
family arrives when, and the report gives the min and max across them.

## The four metrics

Each is defined once, here, and nowhere else.

| Metric | Definition |
| --- | --- |
| **retention** | the share of all 18 checks the final artifact passes |
| **forgetting** | per check, `max(0, max(valid) - valid[-1])` over the checkpoints after it was first measured — `TaskCurve.forgetting`, reused rather than re-derived; reported as mean, max and fraction |
| **transfer** | final minus step 0 on a fresh check set no step ever measured, paired per check and bootstrapped within the seed (`bootstrap_ci`), then min/max across seeds |
| **cost** | check evaluations, ledger commits, artifact bytes/lines and wall clock |

On this domain a fresh check asks the same rule question under a new id — a
different instance of a rule body cannot disagree with it — so transfer equals
retention here, and what the number actually shows is the paired step-0 → final
change (+0.583, interval entirely above zero). A domain whose instances have
variable answers would separate the two; the report carries both, so the
coincidence is visible rather than hidden.

## The gate's blind spot

The gate reads held-out checks only. The default holds out one check per
family (6 of 18), so every family is represented. Lower it and that stops being
true: `--holdout-fraction 0.25` holds out four checks and the report says
`families_without_holdout: [mul_sum, mul_product]` — a rewrite that costs those
families is invisible to the gate, and the bench still records the loss. That
case is pinned by `tests/test_long_horizon_bench.py`, because a forgetting
metric that cannot fire is worse than no metric.

## Verdicts

The vocabulary is `bench.rsi_bench`'s: `insufficient`, `errored`, `hacking`,
`forgetting`, `no-transfer`, `improving`, `regressing`, `flat`. `flat` and
`regressing` are published as verdicts, never omitted. `hacking` cannot fire
here: the domain has no proxy/oracle pair, so `reward_hacking_gap` is `null`
and the report says why.

A step that raises is recorded as `ok: false` with the exception and the loop
continues — `--fail-step K` forces that path. `all_ok` is false and the process
exits `1`, but the report is complete: a long run that dies on step 12 has no
evidence.

## Determinism

Seeds shuffle the arrival order and nothing else; the held-out split is by
stable hash and is the same for every seed. `build_manifest` hashes the spec,
the seeds, the code version and the bench parameters, and two runs of the same
inputs produce the same `manifest_id` and the same report — everything except
`cost.wall_clock_s`, which a test removes before comparing. The temporary
ledgers differ between runs; the measurements do not.
