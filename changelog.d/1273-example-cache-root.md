Fixed
`examples.skill_evolution.download_bbh` and the ADAS hard-subset cache now
write through `dataloader.cache_path`, so they honor `AGENTDESCENT_CACHE` /
`XDG_CACHE_HOME` instead of always mkdir'ing under `~/.cache/agentdescent`
(#1273).
