Fixed
`apply` and its previews now refuse a link planted inside the destination — at
a tree leaf or on the way to one — with the writer's own rule instead of
advertising the write and then exiting on an uncaught `TreeError`: `show
--diff`, `apply --dry-run`, `apply`, `apply --from` and `apply --install-to`
name the same block. The rule is `filetree.dest_problem`, the one
`materialize` enforces, so the preview cannot drift from the write (#1230).
