Fixed
A run clamped to what an operator's Ticket has left now names
`AGENTDESCENT_MAX_CALLS` in its own `stop_detail`, instead of the bare
`cap N` that looked exactly like a caller who had asked for that number;
the same run with no caller cap names it too. The enforced number and the
`call_limit` payload do not change (#1241).
