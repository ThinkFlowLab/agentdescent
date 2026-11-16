Fixed
`traces digest --events FILE` now reads a wrapped `{"events": [...]}` object
(compact or pretty-printed) as the same digest as a JSON array, instead of
reporting a clean bill or exiting 2 (#1119).
