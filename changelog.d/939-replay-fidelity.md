Added
`RunManifest.replay_eligible` / `replay_notes` and an optional `replay` record
(`agentdescent.replay_fidelity.ReplayFidelity`) that captures what a replay needs
and the manifest's input hashes do not cover: RNG seed/state digests at
interaction boundaries, an environment fingerprint (cwd, interpreter, tool
versions, and the sha256 of allowlisted environment names -- `PYTHONHASHSEED`,
`PYTHONPATH`, `LANG`, `LC_ALL`, `TZ`, `OMP_NUM_THREADS`), and hidden-state
digests. Values are never stored, and a credential-shaped name is refused even
when allowlisted. `Trajectory` carries the same record (with `replay_eligible` /
`replay_notes` properties), `ReplayLab(manifest=...)` refuses a counterfactual
with `ReplayNotEligible` naming what was not reconstructed, and `replay_check()`
refuses to compare two runs when either side was not captured (#939).
