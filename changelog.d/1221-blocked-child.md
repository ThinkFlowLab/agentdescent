Fixed
`show --diff` and `apply --dry-run` no longer advertise a tree leaf whose
intermediate path is already a regular file; the preview and the real
`apply` now name the blocking file (`cannot write <leaf>: '<path>' is a
file, not a directory`) instead of listing the leaf as `written` and then
failing the real write with `File exists` (#1221).
