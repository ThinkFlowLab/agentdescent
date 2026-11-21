Fixed
`agentdescent show --diff` and `apply --dry-run` no longer advertise a write
whose nearest existing parent is a regular file; the preview and the real
`apply` now name the blocking file (`cannot write <dest>: '<ancestor>' is a
file, not a directory`) instead of `File exists` on a destination that never
existed (#1208).
