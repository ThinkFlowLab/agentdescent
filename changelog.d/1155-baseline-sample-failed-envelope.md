Fixed
`plan --baseline-sample` now keeps the plan envelope when seed scoring fails
on a provider, subscription, or endpoint error: exit 1 (not 2), `--json`
writes `ok: true`, `ready: false`, a `baseline` object with the failure, and
a `next` repair step (the same wording `plan --probe` already uses), and the
human form keeps the plan plus `next:` / `then:`. Input errors such as
`--baseline-sample 0` still exit 2. No run-store entry is written (#1155).
