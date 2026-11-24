Added
`status` shows a live run's call cap beside its spend — `calls=137/200` — where
it used to print a bare `calls=137`, so a reader can tell 137 of 200 from 137
of 20,000 before the run stops. `RunStatus.calls_cap` is written from the limit
the run actually enforces (the operator ceiling and a Ticket's remainder
included) and omitted from `status.json` when the run has no call cap, so an
uncapped or dollar-only run writes the same bytes as before (#1249).
