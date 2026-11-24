Fixed
The socket-leaf row in `tests/test_apply_non_regular_leaf.py` now binds through
a short root when `tmp_path` rides on a long `TMPDIR`, so the row exercises the
product on every host instead of dying in `bind` with `AF_UNIX path too long` —
the test only, no product behaviour changed (#1245).
