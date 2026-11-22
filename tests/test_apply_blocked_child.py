"""A tree leaf blocked by a regular file is refused before anything is written (#1221).

``#1208`` / ``#1215`` taught every apply surface to refuse a destination whose
nearest existing ancestor is a file. The hole one level down is a *child* of
an otherwise valid tree root: ``dest`` is a directory, ``dest/alpha`` is a
regular file, and the artifact writes ``alpha/SKILL.md``. ``_refuse_blocked_parent``
inspected only ``dest``, so ``show --diff`` and ``apply --dry-run`` advertised
the leaf as ``written`` while the real ``apply`` exited 2 with
``cannot write <dest>: File exists``.

The same ``_check_apply_paths`` funnel now walks every produced path, not just
the root, so the four surfaces agree on the blocking-file sentence and the
preview still writes nothing. ``apply --install-to`` shares that funnel and is
covered here, because no earlier test named the flag on a blocked destination.
"""

from __future__ import annotations

import json

import pytest

from agentdescent import runstore
from agentdescent.cli import main
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "ad-home"))
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)


def _run_cli(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr()


def _blocker(tmp_path):
    p = tmp_path / "blocker"
    p.write_text("keep me\n", encoding="utf-8")
    return p


def _tree_run(tmp_path, dest, state=None):
    store = str(tmp_path / "runs-tree")
    if state is None:
        state = {"alpha/SKILL.md": "evolved\n", "beta/SKILL.md": "evolved\n"}
    rd = runstore.create({
        "kind": "skill_library",
        "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "claude_code"},
        "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state=state, rendered=canonical(state), final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, str(rd.run_id)


def _blocked_message(dest, blocker):
    return f"cannot write {dest}: {str(blocker)!r} is a file, not a directory"


def _show_plan(store, rid, capsys):
    code, out = _run_cli(
        ["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    return json.loads(out.out)["apply_plan"]


def _apply_error(argv, capsys):
    code, out = _run_cli(argv, capsys)
    assert code == 2, out.out or out.err
    doc = json.loads(out.out)
    assert doc["ok"] is False
    return doc["error"]


def test_tree_child_blocked_by_a_file_is_named_on_all_four_surfaces(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    blocker = dest / "alpha"
    blocker.write_text("keep me\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"alpha/SKILL.md": "evolved\n"})
    child = dest / "alpha" / "SKILL.md"
    expected = _blocked_message(child, blocker)
    listing = sorted(p.name for p in dest.iterdir())

    plan = _show_plan(store, rid, capsys)
    show_error = plan.get("error")
    assert show_error, (
        "show advertised a write the real apply refuses: " + json.dumps(plan))
    assert show_error == expected
    assert "written" not in plan
    assert "would_write" not in plan

    code, out = _run_cli(["--store", store, "show", rid, "--diff"], capsys)
    assert code == 0, out.err
    assert show_error in out.out

    dry_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == show_error

    real_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert real_error == show_error, (
        "the preview copied a message apply does not produce")

    assert blocker.read_text(encoding="utf-8") == "keep me\n"
    assert not child.exists()
    assert sorted(p.name for p in dest.iterdir()) == listing


def test_a_sibling_regular_file_does_not_block_a_plain_leaf(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    sibling = dest / "sibling.md"
    sibling.write_text("leave me\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"plain/written.md": "evolved\n"})

    plan = _show_plan(store, rid, capsys)
    assert "error" not in plan, json.dumps(plan)
    assert plan["written"] == ["plain/written.md"]
    assert plan["noop"] is False

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert code == 0, out.err or out.out
    assert json.loads(out.out)["written"] == ["plain/written.md"]
    assert (dest / "plain" / "written.md").read_text(encoding="utf-8") == "evolved\n"
    assert sibling.read_text(encoding="utf-8") == "leave me\n"


def test_apply_install_to_refuses_a_blocked_dest_and_writes_a_clean_one(
        tmp_path, capsys):
    blocker = _blocker(tmp_path)
    blocked = blocker / "lib"
    store, rid = _tree_run(tmp_path, blocked)

    err = _apply_error(
        ["--store", store, "apply", rid, "--install-to", str(blocked), "--json"],
        capsys)
    assert err == _blocked_message(blocked, blocker)
    assert blocker.read_text(encoding="utf-8") == "keep me\n"
    assert not blocked.exists()

    clean = tmp_path / "skills"
    code, out = _run_cli(
        ["--store", store, "apply", rid, "--install-to", str(clean), "--json"],
        capsys)
    assert code == 0, out.err or out.out
    assert (clean / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "evolved\n"
    assert (clean / "beta" / "SKILL.md").read_text(encoding="utf-8") == "evolved\n"
