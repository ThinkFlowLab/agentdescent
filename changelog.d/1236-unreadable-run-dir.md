Fixed
`status`, `show`, `diagnose` and `cancel` now report
`cannot read run '<id>': …` when `status.json` is damaged or the wrong
shape, instead of raising `JSONDecodeError` / `TypeError` out of the MCP
server or as a CLI traceback; a missing `status.json` still says
`no status.json; not a run directory`. `resume` of a damaged run still
refuses with `ok: false` and the Ticket's `cannot be accounted` sentence
(#1236, #1082).
