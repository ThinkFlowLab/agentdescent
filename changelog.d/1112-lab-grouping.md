Changed
`agentdescent --help` now lists the first-run path (`demo`, `init`, `plan`,
`evolve`, `show`, `apply`, `doctor`, `status`) plus `mcp`, and every other verb
is grouped under a new `lab` subcommand (`agentdescent lab campaign …`); each
verb keeps its old top-level path, its arguments, its output and its exit code,
and the same declaration mounts both paths (#1112).
