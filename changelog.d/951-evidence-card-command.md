Added
Every evidence card now says what reproduces it on one `command:` line — an
argv that `python -m tools.evidence_card --check` resolves offline, or
`no offline command -- <why>` when nothing in the repository reproduces the
claim — and the checker refuses a missing or unresolvable one by card name. The
11 published cards gained that line, and
`reports/evidence/results-baselines-plan-runs.json` pins the baselines plan's 18
runs, which `docs/results.md` asserted but nothing checked (#951).
