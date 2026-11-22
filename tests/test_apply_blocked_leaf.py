"""A tree leaf that is already a directory is refused before anything is written (#1223).

``#1221`` / ``#1222`` taught every apply surface to refuse a regular file sitting
on the way to a leaf. The inverse hole is a *directory* sitting where the
artifact wants a file: ``dest`` is a directory, ``dest/alpha`` is a directory
(with ``keep.txt`` inside), and the artifact writes ``alpha``. ``show --diff``
and ``apply --dry-run`` advertised the leaf as ``written`` while the real
``apply`` exited 2 with ``cannot write <dest>: Is a directory`` -- the tree
root, not the blocking leaf.

``apply --from`` was worse: ``shutil.copy2`` dropped the bytes at
``dest/alpha/alpha`` and reported success.

The same ``_check_apply_paths`` funnel now refuses a produced path that exists
as a real directory, so the four surfaces agree on the blocking-directory
sentence and the preview still writes nothing. ``apply --from`` and
``apply --install-to`` share that funnel.
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


def _tree_run(tmp_path, dest, state=None):
    store = str(tmp_path / "runs-tree")
    if state is None:
        state = {"alpha": "evolved\n"}
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


def _blocked_message(leaf):
    return f"cannot write {leaf}: {str(leaf)!r} is a directory, not a file"


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


def test_tree_leaf_blocked_by_a_directory_is_named_on_all_four_surfaces(
        tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    blocker = dest / "alpha"
    blocker.mkdir()
    keep = blocker / "keep.txt"
    keep.write_text("stay\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"alpha": "evolved\n"})
    expected = _blocked_message(blocker)
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

    assert keep.read_text(encoding="utf-8") == "stay\n"
    assert blocker.is_dir()
    assert not (blocker / "alpha").exists()
    assert sorted(p.name for p in dest.iterdir()) == listing


def test_a_nested_leaf_directory_is_named_the_same_way(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    parent = dest / "beta"
    parent.mkdir()
    blocker = parent / "rule.md"
    blocker.mkdir()
    (blocker / "keep.txt").write_text("stay\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"beta/rule.md": "evolved\n"})
    expected = _blocked_message(blocker)

    plan = _show_plan(store, rid, capsys)
    assert plan.get("error") == expected
    assert "written" not in plan

    err = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert err == expected
    assert (blocker / "keep.txt").read_text(encoding="utf-8") == "stay\n"
    assert blocker.is_dir()


def test_a_sibling_directory_does_not_block_a_plain_leaf(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    sibling = dest / "other"
    sibling.mkdir()
    (sibling / "keep.txt").write_text("leave me\n", encoding="utf-8")
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
    assert (sibling / "keep.txt").read_text(encoding="utf-8") == "leave me\n"


def test_apply_from_refuses_a_directory_at_the_leaf_and_writes_a_clean_one(
        tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha").write_text("evolved\n", encoding="utf-8")

    dest = tmp_path / "lib"
    dest.mkdir()
    blocker = dest / "alpha"
    blocker.mkdir()
    keep = blocker / "keep.txt"
    keep.write_text("stay\n", encoding="utf-8")
    expected = _blocked_message(blocker)

    dry_error = _apply_error(
        ["apply", "--from", str(src), "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == expected
    assert keep.read_text(encoding="utf-8") == "stay\n"
    assert not (blocker / "alpha").exists()

    real_error = _apply_error(
        ["apply", "--from", str(src), "--to", str(dest), "--json"], capsys)
    assert real_error == dry_error
    assert keep.read_text(encoding="utf-8") == "stay\n"
    assert blocker.is_dir()
    assert not (blocker / "alpha").exists()
    # No backup of a write that was refused.
    home = tmp_path / "ad-home"
    assert not (home / "backups").exists() or not any(home.joinpath("backups").rglob("*"))

    clean = tmp_path / "clean"
    clean.mkdir()
    code, out = _run_cli(
        ["apply", "--from", str(src), "--to", str(clean), "--json"], capsys)
    assert code == 0, out.err or out.out
    assert json.loads(out.out)["written"] == ["alpha"]
    assert (clean / "alpha").read_text(encoding="utf-8") == "evolved\n"
    assert (clean / "alpha").is_file()


def test_apply_install_to_refuses_a_directory_at_the_leaf(tmp_path, capsys):
    dest = tmp_path / "skills"
    dest.mkdir()
    blocker = dest / "alpha"
    blocker.mkdir()
    keep = blocker / "keep.txt"
    keep.write_text("stay\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"alpha": "evolved\n"})
    expected = _blocked_message(blocker)

    err = _apply_error(
        ["--store", store, "apply", rid, "--install-to", str(dest), "--json"],
        capsys)
    assert err == expected
    assert keep.read_text(encoding="utf-8") == "stay\n"
    assert blocker.is_dir()
    assert not (blocker / "alpha").exists()

    clean = tmp_path / "skills-clean"
    code, out = _run_cli(
        ["--store", store, "apply", rid, "--install-to", str(clean), "--json"],
        capsys)
    assert code == 0, out.err or out.out
    assert (clean / "alpha").read_text(encoding="utf-8") == "evolved\n"
    assert (clean / "alpha").is_file()
