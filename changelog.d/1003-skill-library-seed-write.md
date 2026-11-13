Fixed
The skill-library seed (`init <target> --kind skill_library` and
`algorithms run <name> --kind skill_library`) now refuses an unwritable target
as one `error: cannot write <path>: <reason>` line with exit 2, or
`{"ok": false, "error": ...}` under `--json`, instead of a traceback. Both
destinations are preflighted before anything is written, so a refused `--out`
leaves no seeded `*/SKILL.md` behind; a writable target still seeds its
starters and the `#868` one-starter note is unchanged (#1003).
