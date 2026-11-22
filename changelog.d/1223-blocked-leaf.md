Fixed
`show --diff` and `apply --dry-run` no longer advertise a tree leaf that is
already a directory, and `apply --from` no longer writes inside that
directory; the preview and the real `apply` now name the blocking path
(`cannot write <leaf>: '<leaf>' is a directory, not a file`) instead of
listing the leaf as `written` and then failing the real write with
`Is a directory`, or nesting a file at `<leaf>/<leaf>` (#1223).
