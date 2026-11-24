# Benchmarks you can run

`bench/` is the measurement tree. The modules below each have their own
`__main__` and run on their own; the rest of `bench/` is library code
(`harness.py`, `rsi_bench.py`) with no entry point and no page here.

This page is an index, not a report. It says what each run measures, the command
it takes, whether it runs offline or needs a provider key, and the committed
artefact under `bench/results/` when one exists. What the runs found is on the
bench pages next to this one (`self-evolution-bench.md`,
`long-horizon-bench.md`) and in `results.md`.

`tests/test_bench_index.py` pins the set: every `bench/*.py` with a `__main__`
block must have a row here, and every module named here must exist with one. A
new bench module without a row fails the suite — that is the point of the
page, so add the row in the same change as the module.

`python -m bench` answers the same question in the terminal: one line per
runnable module saying what it measures, then the `python -m bench.<name> --help`
hint. The listing is read off the tree with `ast`, so it imports no bench module
and needs no dataset cache — it works before the heavy runs do. `python -m bench
<name> …` hands the arguments to that module, and an unknown name exits `2` with
the list instead of a traceback.

## Offline — deterministic, no key

| Module | What it measures | Command | Evidence |
| --- | --- | --- | --- |
| `bench/long_horizon.py` | One artifact evolved across dependent steps: retention, forgetting, transfer, cost, with lineage and accept/rollback per step | `python -m bench.long_horizon --steps 9 --seeds 3 --json` | `bench/results/long-horizon-3seed.json` |
| `bench/self_evolution.py` | The whole self-evolution chain, rung by rung, on a deterministic arithmetic domain | `python -m bench.self_evolution --rounds 2 --islands 2 --json` | — |
| `bench/run.py` | The configuration matrix (sync / async, width, lag) on the deterministic router domain | `python -m bench.run --config sync-1 --config sync-4 --config async-4 --budget-calls 400 --seeds 0,1,2` | — |
| `bench/population_engine.py` | Persistent-island population engine against single-head and per-step forks, at equal rollout budget | `python -m bench.population_engine --rounds 12 --seeds 3` | — |
| `bench/ab_replay.py` | DifficultyWeighted vs ReplaySampler task sampling at equal budget, on an echo agent | `python -m bench.ab_replay --budget-rollouts 96 --seeds 0,1,2 --workers 4 --yes` | — |
| `bench/matrix_report.py` | Renders `matrix_run`'s cells as the parallelisation table: serial against the parallel and async arms per algorithm | `python -m bench.matrix_report --json bench/results/matrix-gepa-pilot-ds.json` | reads `bench/results/matrix-*.json` |
| `bench/candidate_methods_report.py` | Renders a candidate-method matrix as a reproducible Markdown report | `python -m bench.candidate_methods_report --input <matrix.json> --output <report.md>` | `bench/results/candidate-methods-framework-final.json` |
| `bench/candidate_methods_merge.py` | Merges disjoint candidate-method matrices without rerunning seeds | `python -m bench.candidate_methods_merge --inputs <a.json> <b.json> --expected-seeds 0 1 2 --output <merged.json>` | `bench/results/candidate-methods-framework-final.json` |

## Key-gated — live model calls

These spend real calls. `--yes` is each module's confirmation gate; without it
the run prints its plan and stops.

| Module | What it measures | Command | Evidence |
| --- | --- | --- | --- |
| `bench/ab_allocator.py` | The value-directed budget allocator against its off control, at equal rollout budget | `python -m bench.ab_allocator --dataset hotpotqa --budget-rollouts 96 --seeds 0,1,2 --provider claude --model <id> --yes` | — |
| `bench/ab_run.py` | The three borrowed RL decision rules (advantage, trust-region, stable-distance) against off | `python -m bench.ab_run --dataset hotpotqa --rule advantage --budget-rollouts 96 --seeds 0,1,2 --provider claude --model <id> --yes` | `bench/results/ab24-advantage.json` |
| `bench/baselines_run.py` | Equal-budget arms (serial, merge-of-N, fork-of-N) as a table on a real dataset | `python -m bench.baselines_run --dataset hotpotqa --budget-rollouts 96 --width 4 --seeds 0,1,2 --provider openai --model <id> --yes --json <out>` | `bench/results/equal-budget-hotpotqa-3seed.json` |
| `bench/candidate_methods.py` | Live runtime matrix over the ported candidate methods: one row per method and mode | `python -m bench.candidate_methods --algorithms aflow reflexion --provider openai --model <id> --yes` | `bench/results/candidate-methods-framework-final.json` |
| `bench/matrix_run.py` | The parallelisation matrix: every port run serial, parallel and async at one pinned budget | `python -m bench.matrix_run --budget 8 --width 8 --seeds 0,1,2 --provider claude --model <id> --json <out> --yes` | `bench/results/matrix-gepa-pilot-ds.json` |
| `bench/metasearch_algotune.py` | Evolves ERA's tree-search selection rule on AlgoTune and validates it on tasks it never saw | `python -m bench.metasearch_algotune --provider openai --model <id> --yes` | `bench/results/metasearch-tree-seed0.json`, `bench/results/era-algotune-model-prior.md` |
| `bench/metasearch_slots.py` | Evolves one `evolve()` decision slot and reports the gain on unseen slices and on another benchmark | `python -m bench.metasearch_slots --slot acceptance --benchmark aime --yes` | `bench/results/metasearch-slots.md`, `bench/results/metasearch-task_sampler-aime-big.json` |
| `bench/openevolve_agentdescent.py` | The OpenEvolve port's serial / sync / async modes at identical model, temperature and call cap | `python -m bench.openevolve_agentdescent --provider openai --model <id> --modes serial sync async` | `bench/results/openevolve-quality-run.json` |

### Which key

`--provider openai` and `--provider glm` read `OPENAI_API_KEY`; `--provider
claude` reads `ANTHROPIC_API_KEY` (`agentdescent/agents.py:737`). Two modules
check the key themselves before spending anything: `bench/candidate_methods.py`
and `bench/openevolve_agentdescent.py` raise `set OPENAI_API_KEY` for
`openai`/`glm`. The two `metasearch_*` modules also take `--dry-run`, which
prints the plan without loading data or calling a model — no key needed.

## Environment notes

- **`$HOME` must be writable.** `agentdescent/dataloader.py` caches datasets
  under `~/.cache/agentdescent`, so on a box with a read-only `$HOME` even
  `--help` fails for a module that loads a dataset at import time. Point `HOME`
  at a scratch directory for those runs.
- **`bench/candidate_methods.py` and `bench/candidate_methods_merge.py` load
  GSM8K at import.** They build their algorithm registry when the module is
  imported, so `--help` needs the data too. With no network and no `pyarrow`,
  set `AGENTDESCENT_GSM8K_SAMPLE=1` for the bundled 96-row sample — module
  names and flags are the same, only the rows differ.
- **Nothing here is a performance claim.** A row says what a run measures and
  how to start it; the numbers live under `bench/results/` and on the bench
  pages.
