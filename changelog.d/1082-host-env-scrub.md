Fixed
A detached run no longer inherits the worker's own session: `runstore.launch`
drops the host-session markers (`SESSION_MARKERS`: `DSH_*`, `CLAUDE*`, `CODEX*`,
`MCP_*`, `OPENAI_AGENT_*` and the OpenCode config carriers) before it starts the
grandchild, so the host worker's session identity and MCP server configuration
stay with the host while the credentials and `PATH` the run needs still pass
through (#1082). The list is the one the candidate worker already dropped
(`agentdescent.agents.worker_env`); the scrub here used to be a second, shorter
copy that dropped only the four prefixes `DSH_`, `CLAUDE`, `CODEX` and `MCP_`,
and five of the eleven crossed it. Four config roots are the one exception
(`DETACHED_KEEP_VARS`: `CLAUDE_CONFIG_DIR`, `CODEX_HOME`, `DSH_HOME`,
`XDG_CONFIG_HOME`): they name configuration rather than session, and the run
resolves a host's real home from them (#1082).
