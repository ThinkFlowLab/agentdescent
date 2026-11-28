Fixed
When MCP `plan(..., probe=true)` succeeds, `next` now names only the
capped `start` (`max_calls` from `estimate.agent_calls_upper_bound`, or
`<N>` when no bound is known), the same already-probed advice the CLI
`plan --probe` already prints, instead of leaving the host without a
`next`. A refused probe and a successful plan without `probe` are
unchanged (#1303).
