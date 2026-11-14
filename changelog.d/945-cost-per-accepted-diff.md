Added
A per-diff `Cost` block (calls, tokens, wall seconds, optional USD), the
`cost_efficiency` / `cost_status` reads, a `CostPolicy` acceptance wrapper that
refuses a quality gain whose cost efficiency regressed (and defers when cost is
required but unmeasured), a `cost_report` with cost per accepted diff and per
point of gain, and `PromotionRules(require_cost=True)` (#945).
