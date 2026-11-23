Fixed
`show --diff` and `apply --dry-run` no longer advertise a tree write whose
backup directory cannot be created, and the real write no longer fails with the
backup's errno printed against a good destination; every surface now names the
blocking path (`cannot write <slot>: '<backup root>' is a file, not a
directory`) before anything is written (#1226).
