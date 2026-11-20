Fixed
A spec whose `evolve` block sets `max_usd` without `usd_per_call` is refused with
`evolve.max_usd needs evolve.usd_per_call beside it` instead of advising a
`--usd-per-call` flag that `compose` refuses before the CLI reads it; the CLI and
run-store wording is unchanged (#1183).
