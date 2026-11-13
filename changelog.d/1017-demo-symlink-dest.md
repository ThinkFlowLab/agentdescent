Fixed
`demo --dir` refuses a symlink planted at a fixture leaf or at `spec.json`
before writing anything, instead of following it and replacing the file outside
the directory: exit 2 with the `cannot write <path>: '<leaf>' is a symlink`
message `init --out` already used, `--json` returning one `{"ok": false}`, and
the named directory left byte-for-byte unchanged (#1017).
