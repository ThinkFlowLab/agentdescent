"""A backup directory that cannot be created is refused before the write (#1226).

``apply`` keeps a tree's previous copy under ``$AGENTDESCENT_HOME/backups``
(``_file_tree_backup_path``, #758). That slot is a path the walk writes, but
``_check_apply_paths`` only ran the operator allowlist guard over it: the
filesystem refusals covered ``dest`` and every ``written`` leaf and stopped
there. So a regular file sitting where the backup root has to be passed both
previews and then killed the real write:

    show --diff / apply --dry-run  -> exit 0, the write advertised
    apply / --install-to           -> ``cannot write <dest>: Not a directory``
    apply --from                   -> ``cannot write <slot>: Not a directory``

The errno belongs to ``$AGENTDESCENT_HOME/backups``, not to ``<dest>`` -- a
destination that is a perfectly good directory -- which is the #1208 defect on
the last leaf of the same walk. ``_refuse_blocked_parent`` runs over the backup
slot now, so all five surfaces name the blocking ancestor before anything is
created.

No ``Fixes`` for another issue: ``#1225`` covers a different leaf of the same
walk (the object at a *written* leaf: FIFO, symlink, directory) and is not
touched here.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import runstore
from agentdescent.cli import main
from agentdescent.evolution import EvolutionResult, _file_tree_backup_path
from agentdescent.filetree import canonical


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "ad-home"))
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)


def _run_cli(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr()


def _text_run(tmp_path, dest, rendered="hello\n"):
    store = str(tmp_path / "runs-text")
    rd = runstore.create({
        "kind": "text", "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact", "agent": {"ref": "echo"}, "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state={}, rendered=rendered, final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, str(rd.run_id)


def _tree_run(tmp_path, dest, state=None):
    store = str(tmp_path / "runs-tree")
    if state is None:
        state = {"alpha/SKILL.md": "evolved\n"}
    rd = runstore.create({
        "kind": "skill_library", "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact", "agent": {"ref": "claude_code"},
        "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state=state, rendered=canonical(state), final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, str(rd.run_id)


def _blocked_root(tmp_path):
    """A regular file where the backup root has to be; unwritable whatever the uid."""
    home = tmp_path / "ad-home"
    home.mkdir()
    root = home / "backups"
    root.write_text("keep me\n", encoding="utf-8")
    return root


def _blocked_message(dest, root):
    """The one message every surface must carry, for the slot apply would take."""
    slot = _file_tree_backup_path(str(dest))
    return f"cannot write {slot}: {str(root)!r} is a file, not a directory"


def _show_plan(store, rid, capsys):
    code, out = _run_cli(["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    return json.loads(out.out)["apply_plan"]


def _apply_error(argv, capsys):
    code, out = _run_cli(argv, capsys)
    assert code == 2, out.out or out.err
    doc = json.loads(out.out)
    assert doc["ok"] is False
    return doc["error"]


def test_tree_surfaces_name_the_blocked_backup_root(tmp_path, capsys):
    root = _blocked_root(tmp_path)
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "alpha").mkdir()
    (dest / "alpha" / "SKILL.md").write_text("old\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest)
    expected = _blocked_message(dest, root)

    plan = _show_plan(store, rid, capsys)
    show_error = plan.get("error")
    assert show_error, (
        "show advertised a write the real apply refuses: " + json.dumps(plan))
    assert show_error == expected
    assert "written" not in plan

    dry_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == show_error

    real_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert real_error == show_error, (
        "the real write named a different path than the preview")

    install_error = _apply_error(
        ["--store", store, "apply", rid, "--install-to", str(dest), "--json"],
        capsys)
    assert install_error == show_error

    # The human `show --diff` prints the same plan, so the line is not JSON-only.
    code, out = _run_cli(["--store", store, "show", rid, "--diff"], capsys)
    assert code == 0, out.err
    assert show_error in out.out

    # Nothing created, nothing overwritten, the blocker untouched.
    assert root.read_text(encoding="utf-8") == "keep me\n"
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "old\n"


def test_apply_from_names_the_blocked_backup_root(tmp_path, capsys):
    root = _blocked_root(tmp_path)
    src = tmp_path / "src"
    (src / "alpha").mkdir(parents=True)
    (src / "alpha" / "SKILL.md").write_text("evolved\n", encoding="utf-8")
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "alpha").mkdir()
    (dest / "alpha" / "SKILL.md").write_text("old\n", encoding="utf-8")
    expected = _blocked_message(dest, root)

    dry_error = _apply_error(
        ["apply", "--from", str(src), "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == expected

    real_error = _apply_error(
        ["apply", "--from", str(src), "--to", str(dest), "--json"], capsys)
    assert real_error == dry_error

    assert root.read_text(encoding="utf-8") == "keep me\n"
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "old\n"


def test_no_backup_writes_a_tree_with_a_blocked_backup_root(tmp_path, capsys):
    """`--no-backup` needs no slot, so the blocker must not refuse the write."""
    root = _blocked_root(tmp_path)
    dest = tmp_path / "lib"
    store, rid = _tree_run(tmp_path, dest)

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--no-backup", "--json"],
        capsys)
    assert code == 0, out.out or out.err
    assert json.loads(out.out)["backup"] == []
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "evolved\n"
    assert root.read_text(encoding="utf-8") == "keep me\n"


def test_a_text_artifact_is_not_refused_by_a_blocked_backup_root(tmp_path, capsys):
    """The text slot sits beside ``dest``; the tree root must not reach it."""
    root = _blocked_root(tmp_path)
    dest = tmp_path / "rule.md"
    store, rid = _text_run(tmp_path, dest)

    plan = _show_plan(store, rid, capsys)
    assert "error" not in plan, json.dumps(plan)

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert code == 0, out.out or out.err
    assert dest.read_text(encoding="utf-8") == "hello\n"
    assert root.read_text(encoding="utf-8") == "keep me\n"


def test_a_creatable_backup_root_still_writes(tmp_path, capsys):
    """The control: a missing (not blocked) backup root is created, not refused."""
    dest = tmp_path / "lib"
    store, rid = _tree_run(tmp_path, dest)

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert code == 0, out.out or out.err
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == "evolved\n"
