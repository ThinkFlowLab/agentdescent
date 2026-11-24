Fixed
`show`, `show --diff`, `apply --dry-run` and `apply` now refuse a `text`
destination that is a named pipe, a socket or a device instead of blocking
forever in `open` while deciding `unchanged`, and `apply --from <file> --to
<path>` refuses the same destination with the same sentence. The four surfaces
name the kind (`'<path>' is a named pipe`) and exit 2 for `apply`, exit 0 with
that sentence in `apply_plan.error` for the previews (#1248).
