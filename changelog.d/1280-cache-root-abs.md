Fixed
`AGENTDESCENT_CACHE` and `XDG_CACHE_HOME` are now read back as absolute paths,
the same half `#403` gave the run store: `cache_path()` no longer returns (or
creates) a bare relative directory, so the dataset cache root is one spelled
path however a later caller was launched. `hf_rows_modelscope`'s docstring
names both knobs instead of one fixed `~/.cache/agentdescent/modelscope/`, and
`runstore.launch` resolves both knobs against the launcher's cwd before the
detached child starts in the run directory, so a relative value names one tree
for the run and for the process that started it (#1280).
