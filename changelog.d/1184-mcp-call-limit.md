Added
The MCP `plan` and `start` tools take `max_calls` and `max_usd`, so a host can
bound a run's model calls per call instead of only through the process-wide
`AGENTDESCENT_MAX_CALLS`. Both validate through the same rule the CLI uses (a
`max_usd` without a price refuses with the CLI's own sentence) and report
`call_limit` with what was asked for and what will be enforced; the operator's
ceiling lowers a caller's number and never raises it, and `start` launches the
detached run under the clamped cap (#1184).
