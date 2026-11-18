Fixed
`manifest.redact` now matches every credential spelling `rsi_telemetry` does:
`PGPASSWORD`, `s3secretkey`, `client_secrets` and the other one-word or plural
forms are redacted before hashing and before a manifest or trajectory record is
written, instead of being stored and hashed in clear. The manifest predicate
keeps its own rules (`bearer`, and the `*_key` suffix that `sort_key` relies on)
and delegates the rest, so a key redacted before still is. Records whose
`model_config` or `extra` carried one of the newly matched spellings get a new
`model_hash` / `spec_hash`, so `verify_manifest` reports those inputs as changed
for them: that is the fix redacting what it used to leak, not a bug (#1100).
