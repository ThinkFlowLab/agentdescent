Added
`agentdescent.pilot` turns one evolution run into one report a user can defend:
the seed and the result are scored on the same disjoint test tasks, the paired
scores become `TrustEvidence`, and `promote()` returns `promote` / `defer` /
`reject` with the reasons, cost, manifest and next action. A test task that
raised is run-health evidence rather than a zero, an unchanged artifact reports
`noise_only`, a missing contamination check defers, and a contaminated dataset
rejects before any model call. `pilot_scores()` exposes the same decision seam
for a run that already happened elsewhere; the CLI and `apply` are separate
follow-ups (#937).
