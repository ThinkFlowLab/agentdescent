Fixed
A successful `init` now names `plan <spec> --probe` in `then:` and `--json`
`next`, the same preflight every other first-run surface already teaches.
When the written spec still has placeholders, that line names `--model` /
`--base-url` (or filling the placeholders) instead of a `plan` that would
exit 2 (#1295).
