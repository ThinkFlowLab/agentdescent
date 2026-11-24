Fixed
Every job in `.github/workflows/*.yml` now declares a finite
`timeout-minutes` instead of inheriting GitHub's 360-minute default: docs
build/deploy 15/15, publish build/publish 15/15, publish-npm publish 15,
and tests test/otel-wire 45/15, each held above the slowest observed run
(`tests` test at 30m12s is why it gets 45, not 30). A hung Pages deploy or
OIDC exchange now fails in the hour it happens rather than holding a
runner for six, and the new `tests/test_workflow_job_timeouts.py` pins
both the invariant and the values (#1235).
