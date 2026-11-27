Fixed
A successful MCP `algorithm_spec` now names `plan(spec, probe=true)` and
a capped `start` (`max_calls` from `estimate.agent_calls_upper_bound`, or
`<N>` when no bound is known) in `next`, instead of telling the host to
`start` unprobed and uncapped. A successful MCP `plan` without `probe`
returns a `next` in the same shape, matching the CLI `plan` next line.
A refused `plan(..., probe=true)` is still `ok: false` / `ready: false`
with a repair `next`. CLI `algorithms run --json` is unchanged (#1296).
