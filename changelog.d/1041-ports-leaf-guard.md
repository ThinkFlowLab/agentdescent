Fixed
`FileArtifactStore` refuses a symlink planted at a leaf it writes instead of
following it: `promote` refuses `<to>` before it reads or removes through it,
and `_commit` refuses `<name>.json` before staging, both as `ValueError:
cannot write <path>: '<leaf>' is a symlink`. The link and the bytes outside
`root` are untouched, and a symlinked directory above the store still works
(#1041).
