Fixed
`trust_evidence` now explains a refused gain that is zero or negative as "the
candidate did not improve on the baseline" instead of blaming the noise floor,
and the note's docstring lists all four causes in code order (#1091).
