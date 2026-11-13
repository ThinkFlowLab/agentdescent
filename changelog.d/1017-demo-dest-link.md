### `demo --dir` refuses a link at a fixture leaf

`agentdescent demo --dir <dir>` wrote every fixture and its `spec.json` with a
plain `open(..., "w")`, so a symlink named exactly like a leaf was followed: the
demo's bytes landed outside `--dir` and the file the link pointed at was
overwritten. The demo now preflights every leaf it is about to write through
`filetree.dest_problem` — the same rule `init` (`#1008`) and the tree writer
(`#977`) already use — and refuses with `error: cannot write …: '<leaf>' is a
symlink` (exit `2`) before the first byte, so a refused run leaves no partial
fixture. A link *above* `--dir` is still allowed.
