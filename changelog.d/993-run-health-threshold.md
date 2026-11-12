Changed
`TrustEvidence` can now carry a `RunHealth` record (`attempted`,
`failed_tasks`, `threshold`): failed tasks are dropped from the paired scores
instead of being folded in as zeroes, so the reported gain is the mean over the
tasks that answered, and a run whose failure rate is above the threshold fails
its eval gate, so `promote()` cannot return `promote`. A bundle built without
health data keeps today's keys, values and hash (#993).
