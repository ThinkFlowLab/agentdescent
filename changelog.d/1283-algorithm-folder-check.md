Fixed
`source_fingerprint` now refuses an `ALGORITHMS` key that names no
`examples/<key>/` directory, instead of silently hashing nothing for
that port, and a test pins each `PROPOSAL_CALLS_PER_CANDIDATE` entry
to the policy's reservation (#1283).
