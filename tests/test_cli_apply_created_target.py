"""``apply`` into a deleted target says it recreated the tree (#1118).

``_write_to``'s plan has no way to record "dest did not exist": a deleted target
came back as ``written``/``backup: []``/``noop: false``, which reads exactly like
an in-place update, and the recreated root is also the one case with nothing to
roll back to. The flag is set on the CLI side (``apply_payload``) and the line is
printed once by ``cmd_apply``.

The in-place row is a pin, not a second red: "never reported as created" and
no line already hold at the base, where the field does not exist at all.
"""

from __future__ import annotations

import json

from agentdescent import cli

from tests.test_skill_library_apply_install import _make_library_run


def test_a_deleted_target_tree_is_created_and_says_so(tmp_path, capsys):
    store, rid = _make_library_run(tmp_path)
    dest = tmp_path / "gone" / "lib"
    assert not dest.exists()

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest),
                     "--dry-run"]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan.get("created") is True
    assert "created " not in cap.err
    assert not dest.exists(), "a dry run writes nothing, this tree included"

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan.get("created") is True
    assert plan["backup"] == []
    assert (dest / "alpha" / "SKILL.md").is_file()
    line = f"created {dest} from run {rid}; nothing was restored and no backup was taken"
    assert cap.err.splitlines().count(line) == 1, cap.err


def test_an_in_place_apply_is_not_reported_as_created(tmp_path, capsys):
    """Pin: an existing target is never reported as created and prints no line."""
    store, rid = _make_library_run(tmp_path)
    dest = tmp_path / "lib"
    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    capsys.readouterr()

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan.get("created", False) is False
    assert "created " not in cap.err
