Changed
A refused probe now prints one JSON contract on every surface: `ok: false`,
`ready: false` and `next` as the repair action. The MCP `plan` tool gains
`ready` (it had only `ok: false`), and `plan --probe --json` /
`algorithms run --probe --json` now set `ok: false` instead of `ok: true`, so a
host reads the same keys and reaches the same verdict whichever surface it
drives (#1175).
