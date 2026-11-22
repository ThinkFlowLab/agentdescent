Fixed
`AGENTDESCENT_MAX_CALLS` is now a budget for one worker session, not a number
each run may ask for again: an MCP `start` after earlier runs is clamped to
what the Ticket has left, reports `call_limit.ticket` with ceiling/spent/
remaining, and refuses outright once the ceiling is spent (#1082). The clamp is
what the run is actually started with, not just what the reply says, and a
started run holds its cap until it reports, so two overlapping starts cannot
both take the remainder (#1082).
