Fixed
The handoff wrapper no longer reports a run that never started as a successful
handoff: when the wait window closes with the child gone and no new
`status.json`, it writes `waiting.json` with `status: failed` and `state:
exited`, and exits nonzero with the child's own reason left in `worker.log`. A
child that is still running and has not written its status yet is unchanged:
`waiting`, `found: false`, exit 0. The page says both (#1096).
