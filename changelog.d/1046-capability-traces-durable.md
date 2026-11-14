Fixed
`capability init --demo` writes its traces fixture through a staging file that
is flushed and fsynced and then renamed into place, so an interrupted run no
longer leaves a partial `capability-traces.jsonl`; the spec is written first,
so an `--out` that names an existing directory no longer leaves the traces
behind beside it (#1046).
