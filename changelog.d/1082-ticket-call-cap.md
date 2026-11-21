Fixed
`AGENTDESCENT_MAX_CALLS` is now a budget for one worker session, not a number
each run may ask for again: an MCP `start` after earlier runs is clamped to
what the Ticket has left, reports `call_limit.ticket` with ceiling/spent/
remaining, and refuses outright once the ceiling is spent (#1082).
