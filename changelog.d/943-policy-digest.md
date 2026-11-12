Added
Every decision record and accepted merge now names the decision procedure that
produced it, as a content hash over the `Policies` bundle, the
decision-relevant `AggregatorConfig` fields and the verifier's knobs:
`policy_digest` on `DecisionRecord`, `MergeContext`, `RunManifest` (`build_manifest`)
and `EvolutionResult`, plus a `policy-digest:` trailer on the ledger's commit
message. A decision taken under a different policy than the previous one for the
same artifact links to it (`parent_id` + `evidence["policy_change"]`), and
`agentdescent.policies.policy_digest()` computes the version for a hand-built
bundle. Additive: absent or empty everywhere by default, unchanged commit
messages and unchanged `manifest_id` (#943).
