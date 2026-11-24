Fixed
The dataset cache root is resolved at call time: `AGENTDESCENT_CACHE` names it
directly, `XDG_CACHE_HOME` puts it under `<XDG_CACHE_HOME>/agentdescent`, and
with neither set it stays `~/.cache/agentdescent`. A dataset-backed port or
bench run no longer dies with `OSError: [Errno 30] Read-only file system` on a
container or CI host whose home is read-only (#1261).
On a read-only-`$HOME` box, point `AGENTDESCENT_CACHE` at a scratch directory
rather than moving `HOME`: `HOME` also moves the Python user site, so the
interpreter can lose its installed packages, while `AGENTDESCENT_CACHE` moves
only the dataset cache.
