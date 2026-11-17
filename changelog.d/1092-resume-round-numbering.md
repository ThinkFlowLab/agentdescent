Fixed
A resumed run continues its ledger's round numbering instead of restarting at
`0`, and `status.best_reward` no longer rewinds below a reward the run's own
history still holds. `execute()` passes one past the last recorded round as the
new `round_base` and seeds the best from the existing rows; a checkpoint further
ahead than the ledger still wins, and an empty ledger still starts at `0`
(#1092).
