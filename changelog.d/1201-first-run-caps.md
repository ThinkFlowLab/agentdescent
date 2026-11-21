Added
The first-run surfaces now name the preflight and the per-call cap that
`docs/start.md` already documents: the shared host skill (and its Claude Code
and DSH renditions) tells a host to pass `max_calls` / `max_usd` on MCP
`plan` / `start` or `--max-calls` / `--max-usd` on the CLI, the
plugin-quickstart habits and the `docs/plugins.md` budget section point at the
same cap beside the older `--budget` overshoot warning, and the `next:` line
from `algorithms run` now reads `plan <spec> --probe, then evolve <spec>
--max-calls N` with N from the plan's own `agent_calls_upper_bound`. The
`demo --algorithm` footer gains the same two steps (`<N>` there: the footer
runs before a spec exists) and `--out spec.json`, so the steps have a path
(#1201).
