"""One refusal walk for every leaf ``apply`` can write (#1230).

``#1215`` (destination blocked by a file), ``#1222`` (tree child blocked by a
file) and ``#1224`` (tree leaf already a directory) each fixed the leaf its
report named. The rules they added all live in ``_check_apply_paths``, the
funnel ``show``, ``apply``, ``--from`` and ``--install-to`` share -- except the
fourth: a *link* planted inside the destination. ``_refuse_blocked_parent``
follows a link to a directory and ``_refuse_blocked_leaf`` deliberately skips
one, so the preview advertised ``written: ["alpha"]`` while the tree writer
raised an uncaught ``TreeError`` traceback out of ``main``.

The rows below are the enumeration, one per leaf: the two link shapes (at the
leaf, on the way to it), then the three earlier shapes as locks, then a legal
sibling as the control that nothing here refuses a destination that works.
"""

from __future__ import annotations

import json
import os

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


def _tree_run(tmp_path, dest, state):
    store = str(tmp_path / "runs-tree")
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


def _same_refusal_on_every_surface(tmp_path, capsys, dest, state, expected):
    """show, dry run and the real write name the same thing; nothing is written."""
    store, rid = _tree_run(tmp_path, dest, state=state)
    before = sorted(os.listdir(dest))

    plan = _show_plan(store, rid, capsys)
    assert plan.get("error") == expected, (
        "show advertised a write the real apply refuses: " + json.dumps(plan))
    assert "written" not in plan

    code, out = _run_cli(["--store", store, "show", rid, "--diff"], capsys)
    assert code == 0, out.err
    assert expected in out.out

    assert _apply_error(
        ["--store", store, "apply", rid, "--dry-run", "--json"], capsys
    ) == expected
    assert _apply_error(
        ["--store", store, "apply", rid, "--json"], capsys
    ) == expected
    assert sorted(os.listdir(dest)) == before
    return store, rid


def _from_error(tmp_path, capsys, dest, files, flag="--to"):
    src = tmp_path / "artifact"
    for rel, text in files.items():
        path = src / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return _apply_error(
        ["apply", "--from", str(src), flag, str(dest), "--json"], capsys)


def test_a_symlinked_leaf_is_named_on_every_surface(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    victim = tmp_path / "victim.md"
    victim.write_text("SECRET\n", encoding="utf-8")
    leaf = dest / "alpha"
    os.symlink(str(victim), str(leaf))

    expected = f"cannot write {leaf}: 'alpha' is a symlink"
    _same_refusal_on_every_surface(
        tmp_path, capsys, dest, {"alpha": "evolved\n"}, expected)
    assert os.path.islink(str(leaf))
    assert victim.read_text(encoding="utf-8") == "SECRET\n"

    # `--from` and `--install-to` walk the same set.
    assert _from_error(tmp_path, capsys, dest, {"alpha": "evolved\n"}) == expected
    assert _from_error(
        tmp_path, capsys, dest, {"alpha": "evolved\n"}, flag="--install-to"
    ) == expected
    assert victim.read_text(encoding="utf-8") == "SECRET\n"


def test_a_symlinked_intermediate_directory_is_named_on_every_surface(
        tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(str(outside), str(dest / "sub"))

    leaf = dest / "sub" / "leaf.md"
    expected = f"cannot write {leaf}: 'sub/leaf.md' is a symlink"
    _same_refusal_on_every_surface(
        tmp_path, capsys, dest, {"sub/leaf.md": "evolved\n"}, expected)
    assert os.path.islink(str(dest / "sub"))
    assert list(outside.iterdir()) == []

    assert _from_error(
        tmp_path, capsys, dest, {"sub/leaf.md": "evolved\n"}) == expected


def test_a_tree_child_blocked_by_a_file_is_named_the_same_way(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    child = dest / "alpha"
    child.write_text("file\n", encoding="utf-8")
    leaf = child / "SKILL.md"
    expected = f"cannot write {leaf}: {str(child)!r} is a file, not a directory"
    _same_refusal_on_every_surface(
        tmp_path, capsys, dest, {"alpha/SKILL.md": "evolved\n"}, expected)
    assert child.read_text(encoding="utf-8") == "file\n"


def test_a_tree_leaf_blocked_by_a_directory_is_named_the_same_way(
        tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    leaf = dest / "beta"
    leaf.mkdir()
    expected = f"cannot write {leaf}: {str(leaf)!r} is a directory, not a file"
    _same_refusal_on_every_surface(
        tmp_path, capsys, dest, {"beta": "evolved\n"}, expected)
    assert leaf.is_dir()


def test_a_destination_blocked_by_a_file_still_refuses(tmp_path, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("file\n", encoding="utf-8")
    dest = blocker / "lib"
    expected = f"cannot write {dest}: {str(blocker)!r} is a file, not a directory"
    store, rid = _tree_run(tmp_path, dest, state={"alpha": "evolved\n"})
    assert _show_plan(store, rid, capsys).get("error") == expected
    assert _apply_error(
        ["--store", store, "apply", rid, "--json"], capsys) == expected
    assert not dest.exists()


def test_a_legal_sibling_survives_the_walk(tmp_path, capsys):
    dest = tmp_path / "lib"
    dest.mkdir()
    keep = dest / "keep.txt"
    keep.write_text("stay\n", encoding="utf-8")
    store, rid = _tree_run(tmp_path, dest, state={"alpha": "evolved\n"})

    code, out = _run_cli(["--store", store, "apply", rid, "--json"], capsys)
    assert code == 0, out.out or out.err
    assert (dest / "alpha").read_text(encoding="utf-8") == "evolved\n"
    assert keep.read_text(encoding="utf-8") == "stay\n"
