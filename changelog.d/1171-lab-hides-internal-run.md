Fixed
`agentdescent lab --help` and the usage line on a `lab` argparse error no
longer list the internal `run` worker in the `{...}` metavar; the verb stays
reachable as `lab run` (#1171).
