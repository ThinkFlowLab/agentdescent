Added
An operator can set `AGENTDESCENT_MAX_CALLS` as a ceiling on the model calls
every run in this process may make. A caller's `--max-calls` lowers it but
cannot raise it, and a run that names no call cap still gets it; a run that
reaches the ceiling ends `done` with `stop_reason="budget"` and a
`stop_detail` naming the variable. Calls only: a dollar ceiling needs a
per-call price, which an un-priced run does not have (#1082).
