Added
MCP `plan` takes `probe: bool = False` and, when true, runs the same
preflight as `plan --probe`: one minimal call per model-backed agent, with the
rows under `probe` in the result. A refusal makes the plan `ok: false` and
points `next` at the repair action instead of `start`, so a host that follows
`next` no longer discovers an expired subscription only after the run exists.
The default is unchanged: plain `plan` still sends nothing and returns its old
key set. The shared host skill teaches the probe step, so every installed
host now asks for it on the first use of a model (#1094).
