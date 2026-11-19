Fixed
A detached run no longer inherits the worker's own session: `runstore.launch`
drops the host-session markers it lists, except the four host config roots it
keeps (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `DSH_HOME`, `XDG_CONFIG_HOME`), before
it starts the grandchild, so the host worker's session identity and MCP server
configuration stay with the host while the credentials and `PATH` the run needs
still pass through (#1082). The marker list is `SESSION_MARKERS` (`DSH_*`,
`CLAUDE*`, `CODEX*`, `MCP_*`, the OpenCode config carriers and
`XDG_CONFIG_HOME`), the one the candidate worker already dropped
(`agentdescent.agents.worker_env`); it used to be a second, shorter copy, and
five of its eleven entries crossed the scrub. Those four roots name
configuration rather than session, and the run resolves a host's real home from
them (#1082).
