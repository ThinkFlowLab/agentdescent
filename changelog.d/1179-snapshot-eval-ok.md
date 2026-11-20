Fixed
`agentdescent snapshot eval --json` now prints `"ok": false` when a task in the
eval failed, instead of always `true` while the command exited 1. The field
matches the exit code again, like the `ok` field every other `--json` verb
derives; `n`, `reward` and `failed` are unchanged (#1179).
