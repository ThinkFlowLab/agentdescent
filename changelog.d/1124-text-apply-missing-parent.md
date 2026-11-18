Fixed
A text-kind `apply <run> --to <fresh>/rule.md` now creates the missing parent
directory before writing, so the dry run it had already reported green is true:
the real run exits 0 and the file lands at that path. A genuinely unwritable
`--to` still exits 2 with the single `error: cannot write …` line (#1124).
