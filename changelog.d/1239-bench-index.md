Added
`docs/bench-index.md` indexes the sixteen `bench/` modules that run on their
own: what each one measures, the command it takes, whether it runs offline or
needs a provider key, and the committed artefact under `bench/results/` when one
exists. `tests/test_bench_index.py` pins the page to the tree in both
directions, so a new bench module without a row fails the suite (#1239).
