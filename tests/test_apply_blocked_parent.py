"""A destination under a regular file is refused before anything is planned (#1208).

``apply`` materialises a missing parent only after the planning path returns:
the text branch creates it just before ``open`` (``cli.py``), ``--from`` does
the same, and a tree goes through ``filetree.materialize``. ``show --diff`` and
``apply --dry-run`` therefore never reached the failing step and advertised a
write that the real ``apply`` exited 2 on -- with ``cannot write <dest>: File
exists``, an errno belonging to the **parent**, printed against a destination
that never existed.

``_check_apply_paths`` is the one funnel every surface already uses (``show``
text, ``apply`` text, ``--from``, ``--install-to`` and the tree writer), so the
refusal lives there and the three surfaces agree by construction. The message
names the blocking ancestor instead of copying the pre-existing text; that is
the intended change for this case, not a ``#1204`` regression (whose "message
bytes unchanged" rule is about the destination refusals).
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
    """A regular file where a directory has to be; unwritable whatever the uid."""
    p = tmp_path / "blocker"
    p.write_text("keep me\n", encoding="utf-8")
    return p


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
    """The one message all three surfaces must carry, derived from the paths."""
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


@pytest.mark.parametrize("rel", ["rule.md", "a/b/rule.md"],
                         ids=["direct-parent", "deep-parent"])
def test_text_show_dry_run_and_apply_name_the_blocking_parent(tmp_path, capsys,
                                                             rel):
    blocker = _blocker(tmp_path)
    dest = blocker / rel
    store, rid = _text_run(tmp_path, dest)
    assert not dest.exists()

    plan = _show_plan(store, rid, capsys)
    show_error = plan.get("error")
    assert show_error, (
        "show advertised a write the real apply refuses: " + json.dumps(plan))
    assert show_error == _blocked_message(dest, blocker)

    dry_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == show_error

    real_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert real_error == show_error, (
        "the preview copied a message apply does not produce")

    # The human `show --diff` prints the same plan, so the line is not JSON-only.
    code, out = _run_cli(["--store", store, "show", rid, "--diff"], capsys)
    assert code == 0, out.err
    assert show_error in out.out

    # Read-only preview, untouched blocker, nothing created in between.
    assert blocker.read_text(encoding="utf-8") == "keep me\n"
    assert not dest.exists()


def test_tree_show_dry_run_and_apply_name_the_blocking_parent(tmp_path, capsys):
    blocker = _blocker(tmp_path)
    dest = blocker / "lib"
    store, rid = _tree_run(tmp_path, dest)

    plan = _show_plan(store, rid, capsys)
    show_error = plan.get("error")
    assert show_error, (
        "show advertised a tree the real apply refuses: " + json.dumps(plan))
    assert show_error == _blocked_message(dest, blocker)

    dry_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == show_error

    real_error = _apply_error(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert real_error == show_error

    assert blocker.read_text(encoding="utf-8") == "keep me\n"
    assert not dest.exists()


def test_apply_from_names_the_blocking_parent(tmp_path, capsys):
    blocker = _blocker(tmp_path)
    dest = blocker / "rule.md"
    source = tmp_path / "incoming.md"
    source.write_text("from file\n", encoding="utf-8")

    dry_error = _apply_error(
        ["apply", "--from", str(source), "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert dry_error == _blocked_message(dest, blocker)

    real_error = _apply_error(
        ["apply", "--from", str(source), "--to", str(dest), "--json"], capsys)
    assert real_error == dry_error

    assert blocker.read_text(encoding="utf-8") == "keep me\n"
    assert source.read_text(encoding="utf-8") == "from file\n"
    assert not dest.exists()


def test_a_creatable_parent_still_writes(tmp_path, capsys):
    """The #1125 control: a missing parent with no blocker is not a refusal."""
    dest = tmp_path / "newdir" / "rule.md"
    store, rid = _text_run(tmp_path, dest)

    plan = _show_plan(store, rid, capsys)
    assert "error" not in plan, json.dumps(plan)
    assert plan["written"] == [str(dest)]
    assert plan["noop"] is False

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--dry-run", "--json"],
        capsys)
    assert code == 0, out.err or out.out
    assert json.loads(out.out)["written"] == [str(dest)]
    assert not dest.parent.exists(), "a dry run writes nothing, parents included"

    code, out = _run_cli(
        ["--store", store, "apply", rid, "--to", str(dest), "--json"], capsys)
    assert code == 0, out.err or out.out
    assert json.loads(out.out)["written"] == [str(dest)]
    assert dest.read_text(encoding="utf-8") == "hello\n"
    assert dest.parent.is_dir()
