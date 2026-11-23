Fixed
`status`, `show`, `diagnose` and `cancel` now report
`cannot read run '<id>': …` when `status.json` is damaged or the wrong
shape, instead of raising `JSONDecodeError` / `TypeError` out of the MCP
server or as a CLI traceback; a missing `status.json` still says
`no status.json; not a run directory` (#1236).
