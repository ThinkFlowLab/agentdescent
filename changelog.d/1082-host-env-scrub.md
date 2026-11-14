Fixed
A detached run no longer inherits the worker's own session: `runstore.launch`
drops the `DSH_*`, `CLAUDE*`, `CODEX*` and `MCP_*` variables before it starts the
grandchild, so the host worker's session identity and MCP server configuration
stay with the host while the credentials and `PATH` the run needs still pass
through (#1082).
