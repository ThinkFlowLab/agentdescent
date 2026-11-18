Added
`plan` can now catch two wasteful runs before they are paid for. The opt-in
`--baseline-sample N` scores the seed artifact on the first N tasks (one agent
call per task, quoted before the first call) and a seed at or above
`--saturation` (default `0.90`) prints `no headroom` and withholds the paid
run's quote unless `--force` is passed; `--json` carries the result as
`baseline` and sets `ready: false`. A plain `plan` still sends nothing.
`plan` and the pilot report also say when the artifact holds one key (a
`SingleSlot` prompt, a one-file tree): worker proposals contradict on that key,
so extra workers buy best-of-N selection, not merging (#1113).
