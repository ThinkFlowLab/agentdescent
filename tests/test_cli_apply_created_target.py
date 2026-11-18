"""``apply`` into a deleted target says it recreated the tree (#1118).

``_write_to``'s plan has no way to record "dest did not exist": a deleted target
came back as ``written``/``backup: []``/``noop: false``, which reads exactly like
an in-place update, and the recreated root is also the one case with nothing to
roll back to. The flag is set on the CLI side (``apply_payload``) and the line is
printed once by ``cmd_apply``.

The in-place row is a pin, not a second red: "never reported as created" and
no line already hold at the base, where the field does not exist at all.

The empty-artifact row is the other way round: green at the base (no such flag
yet), red at ``6be6bbfc``, where ``created = not os.path.isdir(dest)`` was
written unconditionally and the no-op plan returned before
``filetree.materialize`` ever created the directory -- ``created: true`` next to
``noop: true``, plus a line claiming a write that never happened (#1118).
"""

from __future__ import annotations

import json

from agentdescent import cli, runstore
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical

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


def _make_empty_library_run(tmp_path):
    """One completed offline skill_library run whose artifact holds no files."""
    store = str(tmp_path / "runs")
    src = tmp_path / "seed-lib"
    (src / "alpha").mkdir(parents=True)
    (src / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n# alpha\n")
    rd = runstore.create({
        "kind": "skill_library",
        "target": str(src),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "claude_code"},
        "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state={}, rendered=canonical({}), final_reward=0.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, rd.run_id


def test_an_empty_artifact_does_not_claim_to_create_the_target(tmp_path, capsys):
    """``_write_to`` returns a no-op plan before touching a missing dest."""
    store, rid = _make_empty_library_run(tmp_path)
    dest = tmp_path / "gone" / "lib"

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest),
                     "--dry-run"]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan.get("created", False) is False
    assert plan.get("noop") is True
    assert "created " not in cap.err
    assert not dest.exists()

    assert cli.main(["--store", store, "apply", rid, "--to", str(dest)]) == 0
    cap = capsys.readouterr()
    plan = json.loads(cap.out)
    assert plan.get("created", False) is False
    assert "created " not in cap.err
    assert not dest.exists(), (
        "an empty artifact is a no-op and does not create a missing directory")
