Added
A long-horizon bench (`python -m bench.long_horizon`) evolves one playbook
across 5–15 sequential steps on a git ledger, with a deterministic offline
proposer and `DefaultAcceptance` gating each rewrite on held-out checks. It
reports retention, per-check forgetting (mean, max, fraction), paired transfer
on a fresh check set, and cost, alongside the refusals as well as the commits.
On its 3-seed run every seed ends at the domain's reachable ceiling and is
still a `forgetting` verdict, because two check families were erased on the
way (#941).
