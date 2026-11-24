Fixed
`apply --from` now refuses a source tree that holds a non-regular entry, naming
it (`'references/rules.md' is a named pipe`) instead of planning it as a file:
the comparison used to `open` a FIFO and block until a peer appeared, forever
when none did, and a socket or device failed unread. The `--to` side keeps its
old behaviour (#1246).
