Fixed
The label controller no longer adds `agent-pr` to open agent pull requests. The
owner banned the label repo-wide, so the controller's re-add and the label sweep
undid each other on every live run; `risk:T*` is now the only label it adds. The
rule, its reason, the `agentAuthors` / `agentBranchPrefixes` config keys and the
process-doc references are gone, and a dry-run plan proposes nothing for an
`agent/` branch (#1161).
