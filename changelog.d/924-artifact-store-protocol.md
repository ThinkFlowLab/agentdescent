Added
`agentdescent.ports` adds the `ArtifactStore` protocol (`read_tree`/`write_tree`
in bytes, `list_revisions`, a sorted `Diff`, an idempotent `promote`) and
`FileArtifactStore` as the reference backend; an id, revision, parent, promotion
target or path that could leave the store root is refused before any write (#1026).
