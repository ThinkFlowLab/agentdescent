Added
A run-level call cap that holds before the call (`--max-calls`, `--max-usd`,
also `max_calls` / `max_usd` in a spec's `evolve` block) (#1166). Unlike
`max_calls` on `evolve()`, which is a round barrier and lets a four-worker round
overshoot, the guarded cap is charged before each model call: the call that
would cross the limit is not made, the round closes without a partial merge or a
traceback, and the run ends `done` with `stop_reason=budget` and a
`stop_detail` naming the limit and the observed value, in `status.json` and in
`agentdescent status`. `0` is a real limit (no calls); a negative or non-numeric
value is refused at validation with the field and the value named; with neither
flag set the run and `status.json` are unchanged. Offline, no new dependency.
