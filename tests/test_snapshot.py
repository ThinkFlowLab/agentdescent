"""Portable FileTree snapshots reuse the ledger; re-eval does not search."""

import json
from dataclasses import replace

import pytest

from agentdescent.evolution import EvolvingArtifact, Task
from agentdescent.evolvespec import EvolveSpec
from agentdescent.ledger import Ledger, read_artifact_lineage
from agentdescent.artifact_snapshot import (
    ArtifactSnapshot,
    evaluate_snapshot,
    evaluate_snapshot_spec,
)
from agentdescent.treestrategy import FileTree


def _tree():
    files = {
        "SKILL.md": "name: skill\nUse R0 when asked.\n",
        "notes.md": "editable note\n",
        "tests/gold.md": "do not change this fixture\n",
    }
    return FileTree(files, editable=["**"], frozen=["tests/**"])


def _ser(artifact):
    return {"state": dict(artifact.state), "blast_radius": artifact.blast_radius}


def _deser(aid, version, state):
    return EvolvingArtifact(aid, state.get("state", {}), version,
                            state.get("blast_radius", 0.2))


def _ledger(tmp_path):
    return Ledger(str(tmp_path / "repo"), _ser, _deser)


def _tasks():
    return [
        Task(id="t0", prompt="need R0", meta={"rule": "R0"}),
        Task(id="t1", prompt="need R1", meta={"rule": "R1"}),
    ]


def _run(rendered, task):
    return "good" if task.meta["rule"] in rendered else "bad"


def _reward(task, output):
    return 1.0 if output == "good" else 0.0


def test_snapshot_includes_frozen_context_and_roles():
    snap = ArtifactSnapshot.from_filetree(_tree(), artifact_id="skill",
                                          kind="skill_dir")
    assert "tests/gold.md" in snap.files
    assert "SKILL.md" in snap.files
    assert snap.role("tests/gold.md") == "frozen"
    assert snap.role("SKILL.md") == "editable"
    assert snap.to_filetree().writable("tests/gold.md") is False
    assert snap.to_filetree().writable("notes.md") is True


def test_from_filetree_fills_frozen_keys_omitted_from_editable_state():
    tree = _tree()
    editable_only = {p: c for p, c in tree.initial().items()
                     if tree.writable(p)}
    snap = ArtifactSnapshot.from_filetree(
        tree, artifact_id="skill", state=editable_only, kind="skill_dir")
    assert snap.files["tests/gold.md"] == "do not change this fixture\n"
    assert snap.role("tests/gold.md") == "frozen"


def test_json_roundtrip_preserves_lineage_and_files(tmp_path):
    snap = ArtifactSnapshot.from_filetree(
        _tree(), artifact_id="skill", kind="skill_dir",
        lineage={"version": 3, "id": "skill@v3", "parent": "skill@v2",
                 "root": "skill@v1", "commit": "abc", "branch": "dev"})
    path = tmp_path / "skill.json"
    snap.save(path)
    loaded = ArtifactSnapshot.load(path)
    assert loaded.files == snap.files
    assert loaded.id == "skill@v3"
    assert loaded.parent == "skill@v2"
    assert loaded.root == "skill@v1"
    assert loaded.commit == "abc"
    assert loaded.roles() == snap.roles()
    assert loaded.digest() == snap.digest()


def test_lineage_uses_ledger_versions_not_a_second_store(tmp_path):
    led = _ledger(tmp_path)
    first = EvolvingArtifact("skill", _tree().initial())
    led.register(first)
    base = led.head_version(Ledger.DEV)
    second = EvolvingArtifact("skill", {**first.state, "notes.md": "v2\n"})
    led.commit(second, base, branch=Ledger.DEV)
    base = led.head_version(Ledger.DEV)
    third = EvolvingArtifact("skill", {**second.state, "notes.md": "v3\n"})
    led.commit(third, base, branch=Ledger.DEV)

    line = read_artifact_lineage(led.repo_path, "skill", branch=Ledger.DEV)
    assert line["id"] == "skill@v3"
    assert line["parent"] == "skill@v2"
    assert line["root"] == "skill@v1"
    assert line["version"] == 3
    assert line["commit"] and line["parent_commit"] and line["root_commit"]
    assert line["commit"] != line["parent_commit"]
    assert line["root_commit"] != line["commit"]

    snap = ArtifactSnapshot.from_ledger(
        led, "skill", strategy=_tree(), kind="skill_dir")
    assert snap.id == "skill@v3"
    assert snap.parent == "skill@v2"
    assert snap.root == "skill@v1"
    assert snap.files["notes.md"] == "v3\n"
    assert snap.files["tests/gold.md"] == "do not change this fixture\n"
    assert list((tmp_path / "repo").iterdir())  # still one ledger repo


def test_evaluate_snapshot_scores_readonly_and_does_not_search(monkeypatch):
    snap = ArtifactSnapshot.from_filetree(
        _tree(), artifact_id="skill", kind="skill_dir")
    # The frozen tests file is in the candidate even though it is not editable.
    assert "do not change this fixture" in snap.render()

    def boom(*args, **kwargs):
        raise AssertionError("evaluate_snapshot must not call evolve")

    monkeypatch.setattr("agentdescent.artifact_snapshot.evolve", boom, raising=False)
    # Also patch the real engine entry point the scorer might import.
    monkeypatch.setattr("agentdescent.evolution.evolve", boom)

    report = evaluate_snapshot(snap, _tasks(), run=_run, reward=_reward)
    assert report.searched is False
    assert report.n == 2
    assert report.scores["t0"] == 1.0
    assert report.scores["t1"] == 0.0
    assert report.reward == 0.5
    assert report.failed == ()


def test_evaluate_snapshot_spec_uses_dest_tasks_and_rejects_kind_mismatch():
    snap = ArtifactSnapshot(
        artifact_id="skill", kind="text",
        files={"skill": "answer with yes"},
        rendered="answer with yes",
    )
    dest = EvolveSpec(
        kind="text", target="ignored-target",
        data={"inline": [
            {"id": "a", "prompt": "say yes", "gold": "yes"},
            {"id": "b", "prompt": "say yes again", "gold": "yes"},
        ]},
        score="contains", agent="echo",
        evolve={"rounds": 8, "n_workers": 4},
    )

    def boom(*args, **kwargs):
        raise AssertionError("spec re-eval must not search")

    import agentdescent.evolvespec as es
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(es, "run_spec", boom)
    monkeypatch.setattr("agentdescent.evolution.evolve", boom)
    try:
        report = evaluate_snapshot_spec(snap, dest)
    finally:
        monkeypatch.undo()

    assert report.searched is False
    assert report.n == 2
    assert report.reward == 1.0

    other = replace(dest, kind="skill_dir")
    with pytest.raises(ValueError, match="not compatible"):
        evaluate_snapshot_spec(snap, other)


def test_plugin_kind_snapshot_is_the_plugin_tree_not_a_host():
    files = {"plugin.py": "print('plugin')\n", "README.md": "a plugin\n"}
    snap = ArtifactSnapshot.from_filetree(
        FileTree(files, frozen=["README.md"]),
        artifact_id="my-plugin", kind="plugin")
    assert snap.kind == "plugin"
    assert snap.files["plugin.py"].startswith("print")
    assert snap.role("README.md") == "frozen"
    # Plugin kind is the evolved artifact, not a host execution environment.
    assert "claude" not in json.dumps(snap.to_dict())
