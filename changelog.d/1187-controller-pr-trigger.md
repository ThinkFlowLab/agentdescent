Changed
The label-only controller now also runs on the `pull_request` `opened`,
`ready_for_review` and `reopened` events, so a new PR is labelled immediately
instead of waiting for the throttled `schedule` tick; the cron stays as the
fallback, and a `pull_request` run from a fork head is skipped by both jobs
because it cannot hold a write token (#1187).
