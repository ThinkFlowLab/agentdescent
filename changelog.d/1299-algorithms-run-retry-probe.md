Fixed
When `algorithms run` writes a spec and `plan` refuses it, the human
`next:` line and `--json` `next` now name `plan <spec> --probe`, the same
preflight a successful run already teaches, instead of a bare `plan`.
The retry still does not recommend `evolve` (#1299).
