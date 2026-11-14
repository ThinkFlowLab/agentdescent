Fixed
`algorithm_spec` now checks its spec destination against the operator's surface
write allowlist before writing, like `apply` and the other write tools: an `out`
outside `AGENTDESCENT_SURFACE_WRITE_DIRS` returns `ok: false` and nothing is
written (#1018).
