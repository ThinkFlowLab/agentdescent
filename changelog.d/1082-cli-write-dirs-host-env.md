Fixed
`agentdescent apply` and `show --diff` now obey
`AGENTDESCENT_SURFACE_WRITE_DIRS` instead of only the MCP surface doing so: a
destination outside the operator's allowlist is refused before the first byte,
and the advertised `apply_plan` carries that refusal rather than a path the
worker cannot write. Unset keeps the CLI as it was; an empty value refuses
every write. A detached run also no longer inherits the host session's
`DSH_*`, `CLAUDE*`, `CODEX*` or `MCP_*` variables, while the credentials it
needs still pass through (#1082).
