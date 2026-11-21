"""``show --diff`` must preview every destination ``apply`` refuses (#1204).

``#1200`` taught the preview about the operator write-dir boundary. The other
half of ``apply``'s destination refusals was still missing: a text artifact
whose target is a directory or a symlink, and a tree whose root is a symlink.
``show`` advertised those writes (``written``, no ``error``) while ``apply``
exited 2. The preview must carry ``apply``'s own message, stay read-only, and
exit 0.
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


def _text_run(tmp_path, dest, rendered="hello\n"):
    store = str(tmp_path / "runs")
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
    store = str(tmp_path / "runs")
    if state is None:
        state = {"alpha/SKILL.md": "evolved\n"}
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


def _assert_show_matches_apply(store, rid, capsys):
    """``show --diff --json`` reports ``apply``'s own refusal and exits 0."""
    code, out = _run_cli(
        ["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    plan = json.loads(out.out)["apply_plan"]
    show_error = plan.get("error")
    assert show_error, "show advertised a write apply would refuse: " + json.dumps(plan)

    code, out = _run_cli(["--store", store, "apply", rid, "--json"], capsys)
    assert code == 2, out.out or out.err
    apply_payload = json.loads(out.out)
    assert apply_payload.get("ok") is False
    assert show_error == apply_payload["error"]
    return show_error


def test_show_previews_the_directory_refusal_for_a_text_artifact(tmp_path, capsys):
    dest = tmp_path / "outdir"
    dest.mkdir()
    marker = dest / "keep.txt"
    marker.write_text("stay\n", encoding="utf-8")
    store, rid = _text_run(tmp_path, dest)

    _assert_show_matches_apply(store, rid, capsys)

    assert dest.is_dir()
    assert marker.read_text(encoding="utf-8") == "stay\n"
    assert sorted(p.name for p in dest.iterdir()) == ["keep.txt"]


def test_show_previews_the_symlink_refusal_for_a_text_artifact(tmp_path, capsys):
    real = tmp_path / "real.txt"
    real.write_text("secret\n", encoding="utf-8")
    dest = tmp_path / "link.txt"
    os.symlink(str(real), str(dest))
    store, rid = _text_run(tmp_path, dest)

    error = _assert_show_matches_apply(store, rid, capsys)

    assert "destination link is never dereferenced" in error
    assert os.path.islink(str(dest))
    assert real.read_text(encoding="utf-8") == "secret\n"


def test_show_previews_the_symlink_root_refusal_for_a_tree_artifact(tmp_path, capsys):
    real = tmp_path / "real-root"
    real.mkdir()
    (real / "SKILL.md").write_text("original\n", encoding="utf-8")
    dest = tmp_path / "link-root"
    os.symlink(str(real), str(dest))
    store, rid = _tree_run(tmp_path, dest)

    error = _assert_show_matches_apply(store, rid, capsys)

    assert "destination link is never dereferenced" in error
    assert os.path.islink(str(dest))
    assert (real / "SKILL.md").read_text(encoding="utf-8") == "original\n"
    assert list(real.iterdir()) == [real / "SKILL.md"]


def test_show_still_reports_a_regular_file_text_plan(tmp_path, capsys):
    dest = tmp_path / "prompt.txt"
    dest.write_text("old\n", encoding="utf-8")
    store, rid = _text_run(tmp_path, dest, rendered="new text\n")

    code, out = _run_cli(
        ["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    plan = json.loads(out.out)["apply_plan"]
    assert plan.get("error") is None
    assert plan["written"] == [str(dest)]
    assert plan["noop"] is False
    assert dest.read_text(encoding="utf-8") == "old\n"
