Fixed
`AGENTDESCENT_MAX_CALLS` is now a budget for one worker session, not a number
each run may ask for again: an MCP `start` after earlier runs is clamped to
what the Ticket has left, reports `call_limit.ticket` with ceiling/spent/
remaining, and refuses outright once the ceiling is spent (#1082). The clamp is
what the run is actually started with, not just what the reply says, and a
started run holds its cap until it reports, so two overlapping starts cannot
both take the remainder (#1082).

A run whose status cannot be read is no longer counted as free: the Ticket
refuses to start or resume anything until the run store is readable again,
instead of granting a remainder that may already be spent. A `max_usd` without
`usd_per_call` is still refused with the argument named in the message, now
from inside the same gate (#1196).

`resume` shares the same Ticket remainder as `start`: a run this server started
is relaunched with its ledger plus what is left, and a run it did not start is
registered and charged on its first resume here, its whole earlier ledger
counted, with no grant once that ledger fills the remainder.
