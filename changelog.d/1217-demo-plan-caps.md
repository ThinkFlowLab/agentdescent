Fixed
The default `demo` footer (and `demo --kind skill_library`) and a successful
bare `plan` now name the same first-run preflight and per-call cap that
#1212 already put on `algorithms run` / `demo --algorithm`: after `init`
and `doctor`, `plan spec.json --probe`, then `evolve spec.json --max-calls
<N>` (a placeholder on the demo, which has no user estimate yet). Bare
`plan` recommends `evolve --max-calls N` from its own
`estimate.agent_calls_upper_bound`, names `plan --probe` first when this
invocation did not already probe, and `--json` carries the same `next`
string. A refused probe still prints the repair plus `then: plan --probe`
(#1175 / #1093) (#1217).
