Fixed
When MCP `algorithm_spec` writes a spec that then fails to plan, `next`
now names a fix of the written spec and then `plan(..., probe=true)` in
tool language, instead of the CLI retry `agentdescent plan <path>
--probe`. A successful `algorithm_spec` next and the CLI
`algorithms run` failed-plan next are unchanged (#1305).
