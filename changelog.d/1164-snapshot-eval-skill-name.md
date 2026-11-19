Fixed
`snapshot eval` of a `skill_dir` snapshot now exposes the candidate under
the snapshot's `artifact_id` in the destination layout (for example
`.claude/skills/csv-total/`), so a demo export re-evaluated with `--spec`
scores the learned skill instead of 0 because the dest agent looked under
`.claude/skills/artifact/` (#1164).
