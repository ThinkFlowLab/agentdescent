Fixed
A claim no longer expires under a pull request that links its issue with
`Refs #N` or `Part of #N`: the controller now reads those references when it
decides whether the claim's TTL is still fed by a push, while only closing
keywords still make a PR an agent PR (#1161).
