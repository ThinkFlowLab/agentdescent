Fixed
A promoting multi-seed pilot report no longer tells the reader to "review the
artifact diff" or "apply it" when the seeds produced different artifacts and the
report names none. The steps point at `run.per_seed` and ask for one seed's
artifact to be chosen, reviewed and applied as an explicit step; the single-seed
and agreeing-seed reports keep their current text (#1141).
