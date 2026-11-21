Fixed
The MCP `plan` / `start` tools no longer answer an unpriced `max_usd` with the
CLI's `--usd-per-call` sentence: they now name `usd_per_call`, the argument the
host passes in the same tool call. A Python `runstore.launch` / `execute` caller
is told to set `usd_per_call` beside it, and the command line keeps its own
sentence unchanged (#1196).
