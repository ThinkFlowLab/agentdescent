Fixed
`EvolutionResult.write_to` keeps directory backups under
`$AGENTDESCENT_HOME/backups/` (else `~/.agentdescent/backups/`) instead of a
sibling `<path>.bak-N`, so host skill scanners (OpenCode, Claude Code) no longer
load the backup and shadow the evolved skill after `apply` (#758).
