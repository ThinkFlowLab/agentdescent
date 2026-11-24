Fixed
`show --diff`, `apply --dry-run` and `apply` now refuse a tree leaf that is a
FIFO, a socket or a device instead of advertising it as `written`: the preview
and the write both name the blocking path (`cannot write <leaf>: '<leaf>' is a
named pipe`). `apply --no-backup` no longer blocks in `open(..., "w")` after
writing the leaves that sort before the blocking one, and `load_tree` refuses a
non-regular entry instead of blocking on it, so `show --diff` returns too
(#1225).
