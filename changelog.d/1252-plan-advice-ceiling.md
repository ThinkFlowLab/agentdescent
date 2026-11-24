Fixed
`plan`'s `next:` line, `--json.next` and `warnings` now name the smallest of
the structural bound, the spec's declared cap and the operator ceiling, so a
2-call `AGENTDESCENT_MAX_CALLS` no longer advises `--max-calls 52` for a run
that stops after two calls; the warning reads
`AGENTDESCENT_MAX_CALLS=2 caps this run at 2 calls; the plan estimates 52`.
A spent Ticket makes the MCP `plan` tool refuse in `start`'s exact sentence
instead of reporting `ok: true` with `max_calls: 0`. The estimate, the
`call_limit` numbers and every stop reason are unchanged (#1252).
