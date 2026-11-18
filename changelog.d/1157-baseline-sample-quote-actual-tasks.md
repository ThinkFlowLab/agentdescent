Fixed
`plan --baseline-sample` now quotes the number of tasks the sample can
actually score, not the requested N: a 4-task spec asked for 50 is priced
at 4 calls, and that count matches `baseline.sample`. A request below the
task count is unchanged (#1157).
