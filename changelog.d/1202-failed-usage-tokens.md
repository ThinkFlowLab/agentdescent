Fixed
A failed model call now records the tokens its provider reported -- a 4xx body,
or a stream that died after its last chunk -- so the run's totals and the
`max_tokens` meter no longer under-report what was spent. `Usage` gains
`failed_usage_attempts` and `failed_usage_tokens`, which report that part of
the bill; both are additive fields with defaults, and the accounting basis is
unchanged (#1202).
