Changed
The label-only controller now also runs on the `pull_request` `opened`,
`ready_for_review` and `reopened` events, so a new PR is labelled immediately
instead of waiting for a `schedule` tick. The cron moves from every 30 minutes
(48 declared slots, in practice two or three runs a day) to `17 */6 * * *`, a
backstop only; a `pull_request` run from a fork head is skipped by both jobs
because it cannot hold a write token (#1187).
