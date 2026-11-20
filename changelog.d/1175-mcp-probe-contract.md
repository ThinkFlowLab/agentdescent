Changed
A refused probe now prints one JSON contract on every surface: `ok: false`,
`ready: false` and `next` as the repair action. The MCP `plan` tool gains
`ready` (it had only `ok: false`), and `plan --probe --json` /
`algorithms run --probe --json` now set `ok: false` instead of `ok: true`, so a
host reads the same keys and reaches the same verdict whichever surface it
drives (#1175).

This supersedes the 0.11.0 entry (#1093), which said: "`--json` sets
`ready: false` while leaving `ok` about the plan itself, and a successful or
omitted probe is unchanged (#1093)." It now sets `ok: false` too, on both
surfaces, because a refusal is not success anywhere; a successful or omitted
probe is still unchanged.
