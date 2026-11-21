Fixed
`agentdescent show --diff` previews every destination `apply` refuses, not
only the write-dir boundary: a text artifact whose target is a directory or
a symlink, and a tree whose root is a symlink, now appear as
`apply_plan.error` with `apply`'s own message, and `show` stays read-only
(#1204).
