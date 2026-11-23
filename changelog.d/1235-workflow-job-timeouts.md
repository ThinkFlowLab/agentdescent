Fixed
Every workflow job now declares a `timeout-minutes` -- 5 or 10 for the short
report, build and publish jobs, 60 for the five-version `tests` matrix -- so a
stalled deploy, publish or test run fails in minutes instead of holding a
runner for GitHub's 360-minute default (#1235).
