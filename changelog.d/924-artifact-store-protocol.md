Added
`agentdescent.ports` defines the `ArtifactStore` protocol — `read_tree` /
`write_tree` in bytes, `list_revisions`, a sorted `Diff`, and an idempotent
`promote` — with `FileArtifactStore` as the reference directory backend. An
artifact id, revision, parent or promotion target that could leave the store
root is refused with `ValueError` before anything is written (#1026).
