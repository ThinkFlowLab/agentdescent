Fixed
`agentdescent capability init --demo` refuses a symlink planted at
`capability-traces.jsonl` or at `--out` before the first byte, instead of
following the link and destroying the file it points at; the `--out` refusal no
longer leaves a half-written traces fixture behind (#1043).
