# Cost per accepted diff

> **Quality is one axis; the price of the diff is the other.** A candidate that
> adds +0.10 for five times the tokens can beat one that adds +0.09 for 1.1x if
> the gate only reads the held-out number. This page is the second ledger: what
> one diff cost, what that buys, and when a quality gain is refused because its
> efficiency regressed.

## 1. What a diff costs

`Cost` is the per-diff price block. Every field is optional on purpose:

| field | meaning | where it comes from |
|---|---|---|
| `calls` | model calls spent producing the diff | `agents.Usage.calls` |
| `prompt_tokens` / `completion_tokens` | the provider's real split | `agents.Usage` |
| `tokens` | total when only a total is known (an evidence card records one) | `EvidenceCard.cost_tokens` |
| `wallclock` | seconds spent | `Usage.seconds` / `EvidenceCard.cost_wallclock` |
| `usd` | a dollar estimate the caller measured | caller-supplied |

```python
from agentdescent import Cost, cost_efficiency, cost_status

cost = Cost.from_usage(usage, usd=0.03)      # real counts, caller's price
print(cost.tokens, cost.usd)
print(cost_efficiency(0.10, cost))           # held-out delta per 1k tokens
print(cost_status(cost_efficiency(0.10, cost), 0.05))   # improved/neutral/…
```

**A missing number is `None`, never `0`.** Zero is a measurement ("this diff was
free"); an unmeasured field is not. `Cost().known` is `False`, and every derived
value (`cost_efficiency`, the report's per-accepted fields) stays `None` rather
than pretending the diff was free. `Cost.from_cards` sums what the contributing
[evidence cards](data-model.md) already record for one working diff.

`usd` is whatever the caller measured. There is no provider price table and no
billing in this repository: an unpriced run leaves `usd=None` and still reports
tokens.

## 2. The acceptance option

`CostPolicy` is a wrapper, not a replacement. It runs the inner gate first and
returns its rejection untouched — a cheap candidate the quality gate refused is
still refused. It only prices candidates that were *about* to commit:

```python
from agentdescent import CostPolicy, DefaultAcceptance

acceptance = CostPolicy(
    DefaultAcceptance(),
    reference_quality_per_cost=0.05,   # per 1k tokens, from an earlier accepted diff
    tolerance=0.05,                    # a 5% wobble is neutral, not a verdict
    require_cost=True,                 # no measurement -> defer, not "free"
)
```

| field | what it decides |
|---|---|
| `reference_quality_per_cost` | refuse when the measured `quality_per_cost` regressed against this reference, even though raw quality rose |
| `min_gain_per_1k_tokens` | refuse when efficiency is below an absolute floor |
| `tolerance` | dead band around the reference, so noise-sized wobbles are `neutral` |
| `require_cost` | with no measured cost, `defer` (`category="cost-unknown"`) instead of pricing it at zero |

A refusal is `AcceptDecision(accept=False, category="cost-regression")` and
names the measured efficiency, the reference and the gain in `detail`; the cost
block (with `status`) is on `provenance["cost"]`. The decision that a cost
*regressed* is a refusal, not a rejection of the candidate's quality: the
quality gain is real, it just did not pay for itself.

The cost the policy reads is `MergeContext.diff_cost` when the caller measured
one; otherwise it is `Cost.from_cards` over the cards that justify the diff —
the usage the loop already records per working diff.

## 3. The report

`cost_report` turns decision records into the two numbers a review needs — cost
per **accepted diff** and cost per **point of gain** — and counts missing cost
instead of zeroing it:

```python
from agentdescent import cost_report

report = cost_report(decisions, reference_tokens_per_point=20_000)
print(report.tokens_per_accepted, report.usd_per_accepted)
print(report.tokens_per_point, report.cost_status)   # improved/neutral/regressed/unknown
```

Each record is a mapping (or object) with `accepted: bool`, an optional `gain`
(held-out delta) and an optional `cost`. Spend covers every decision, so
`tokens_per_accepted` is the amortised price of one accepted diff; the
per-point fields divide by the accepted positive gains. `missing_cost` counts
accepted diffs that carried no usable cost, and `cost_status` is `unknown`
without a reference — there is no scale to call anything better or worse
against.

## 4. The promotion bar

`PromotionRules(require_cost=True)` is the fail-closed bar on the promotion
side. A `PromotionRequest` without a measured `cost` (or with an all-`None`
`Cost`) defers with `cost` in `missing`; it is never treated as zero and never
a rejection. With the default `require_cost=False`, requests without cost keep
exactly the decision and hashes they had before this feature.

## 5. What is not here

Provider billing, a price table, a claim that tokens are the only cost axis, and
the `PilotReport` fields — `agentdescent/pilot.py` does not exist yet (#937), so
`CostReport` is the report surface in this slice.
