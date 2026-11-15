Fixed
`docs/cost.md` no longer says the gate prices a diff from usage the loop already
records on the evidence cards. Nothing in this tree fills
`EvidenceCard.cost_tokens` or `cost_wallclock`, so the `Cost.from_cards`
fallback is an unknown `Cost()`, and a caller that wants a priced diff passes
`MergeContext.diff_cost = Cost.from_usage(usage)`. The page now warns that
`require_cost=True` defers every candidate on such a run, and that
`reference_quality_per_cost` and `min_gain_per_1k_tokens` cannot refuse
anything without a measured cost (#1085).
