Fixed
`--json evolve` and `--json show` now include `stop_detail` when a run-level
cap stopped the run, so the machine output names the limit that fired instead
of only `"stop_reason": "budget"`. The key is omitted when no cap tripped, so
an uncapped payload keeps its previous shape (#1190).
