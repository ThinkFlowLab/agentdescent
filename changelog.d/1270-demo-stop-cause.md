Fixed
The demo footer names the limit that stopped the run instead of reporting the
result as "lower than expected for the demo": a run halted by
`AGENTDESCENT_MAX_CALLS` (or another cap) now prints the recorded
`stop_detail`, and `demo --json` carries the same cause in `note` (#1270).
