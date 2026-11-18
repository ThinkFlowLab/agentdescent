"""A text ``apply --to`` into a missing parent writes, like the tree branch (#1124).

The dry run asked ``_text_plan`` only whether ``dest`` already held the text, so a
missing parent was invisible to it: the plan said ``written`` and the real run
died at ``open`` with ``error: cannot write ...: No such file or directory``,
writing nothing. ``apply --from`` already creates the parent before ``open``
(``cli.py``, the ``--from`` branch); this is the run-store branch catching up,
not a second rule.

The reverse row is a pin, not a red: a genuinely unwritable ``--to`` must keep
the one-line refusal from `#990` -- see ``tests/test_cli_write_error.py``, whose
rows are left exactly as they are.
"""

from __future__ import annotations

import json

from agentdescent import cli

from tests.test_cli_write_error import _text_run


def test_a_text_apply_creates_a_missing_parent(tmp_path, capsys):
    """Dry run true, real run 0: the file lands and its parent is made."""
    store, rid = _text_run(tmp_path)
    dest = tmp_path / "newdir" / "rule.md"
    assert not dest.parent.exists()

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest),
                     "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["written"] == [str(dest)]
    assert plan["noop"] is False
    assert not dest.parent.exists(), "a dry run writes nothing, parents included"

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    assert dest.read_text(encoding="utf-8") == "evolved rule\n"
    assert dest.parent.is_dir()


def test_a_text_apply_into_an_unwritable_parent_is_still_one_line(tmp_path,
                                                                  capsys):
    """Pin #990 for the text branch: exit 2, one line, no traceback."""
    store, rid = _text_run(tmp_path)
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory\n", encoding="utf-8")
    dest = blocked / "rule.md"

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 2

    cap = capsys.readouterr()
    assert "Traceback" not in cap.err and "Traceback" not in cap.out
    assert cap.out == ""
    lines = [ln for ln in cap.err.strip().splitlines() if ln]
    assert len(lines) == 1, cap.err
    assert lines[0].startswith(f"error: cannot write {dest}: ")
