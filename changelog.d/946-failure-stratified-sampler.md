Added
`FailureStratifiedSampler` stratifies tasks by base failure signature, keeps
search/select/final sets disjoint, and reports stratum coverage, overlap and
transfer status so one dominant failure mode cannot take over the search set
(#946).
