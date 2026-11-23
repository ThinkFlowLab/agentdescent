Fixed
Installed `/evolve` and `/algorithms run` slash commands (and the MCP
`algorithm_spec` description) now name the same first-run `plan --probe` /
`probe=true` preflight and `max_calls` / `--max-calls` cap as `SKILL.md`
and the CLI `next:` line, so a host following the command no longer starts
a first real run without them. Claude / Codex / OpenCode command files stay
byte-identical (#1228).
