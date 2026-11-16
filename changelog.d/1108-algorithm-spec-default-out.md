Fixed
`algorithm_spec` no longer defaults its starter spec to a path beside the
user's target, which the default write allowlist refused: an omitted `out` now
writes `agentdescent.<name>.spec.json` under `$AGENTDESCENT_HOME` (or the first
explicitly allowed root), so the shortest documented path plans on an untouched
install. The tool description and the shared `SKILL.md` say so, and a refused
explicit `out` names the allowed roots and an `out` that works (#1108).
