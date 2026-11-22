Fixed
`plan`'s `next:` line no longer raises a call cap the spec already declares: a
spec with `evolve.max_calls` is advised at `min(bound, declared)`, a spec with
`max_usd` + `usd_per_call` gets no `--max-calls` at all (also when it declares
both, since a flag would replace that dollar cap), and `--json.next` is the
same string. The `estimate.agent_calls_upper_bound` reading is unchanged
(#1219).
