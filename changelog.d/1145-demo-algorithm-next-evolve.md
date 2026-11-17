Fixed
`demo --algorithm NAME` no longer ends with `evolve agentdescent.NAME.spec.json`.
That file does not exist until `algorithms run` writes it, so following the
footer (or `--json` / MCP `next`) failed with exit 2. The footer still points
at `algorithms run NAME ...`, which plans and then prints `evolve` with the
absolute path it just wrote (#1145).
