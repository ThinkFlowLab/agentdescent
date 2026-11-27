Fixed
When `algorithms run --probe` succeeds, the human `next:` line and
`--json` `next` now name only the capped `evolve`, the same advice
`plan --probe` already prints, instead of asking to probe again.
A refused probe and a flagless `algorithms run` are unchanged (#1301).
