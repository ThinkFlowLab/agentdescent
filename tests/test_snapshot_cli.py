"""CLI surface for portable snapshots: show, eval, apply — no search."""

import json
from pathlib import Path

from agentdescent.cli import main
from agentdescent.artifact_snapshot import ArtifactSnapshot
from agentdescent.treestrategy import FileTree


def _snap(path: Path) -> ArtifactSnapshot:
    snap = ArtifactSnapshot.from_filetree(
        FileTree({"SKILL.md": "always say yes\n", "tests/n.txt": "frozen\n"},
                 frozen=["tests/**"]),
        artifact_id="skill", kind="text",
        lineage={"version": 2, "id": "skill@v2", "parent": "skill@v1",
                 "root": "skill@v1"})
    # text re-eval uses render(); keep the instruction body.
    return ArtifactSnapshot(
        artifact_id=snap.artifact_id, files=snap.files, editable=snap.editable,
        frozen=snap.frozen, kind="text", version=2, id="skill@v2",
        parent="skill@v1", root="skill@v1", rendered="always say yes")


def test_snapshot_show_export_eval_and_apply(tmp_path, capsys, monkeypatch):
    snap = _snap(tmp_path)
    source = tmp_path / "skill.json"
    snap.save(source)

    assert main(["--json", "snapshot", "show", str(source)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["id"] == "skill@v2"
    assert shown["parent"] == "skill@v1"
    assert shown["roles"]["tests/n.txt"] == "frozen"

    out = tmp_path / "exported.json"
    assert main(["snapshot", "export", str(source), "-o", str(out)]) == 0
    capsys.readouterr()  # "wrote …" on stdout
    assert ArtifactSnapshot.load(out).id == "skill@v2"

    dest = tmp_path / "dest.json"
    dest.write_text(json.dumps({
        "kind": "text", "target": "ignored",
        "agent": "echo", "score": "contains",
        "data": {"inline": [
            {"id": "a", "prompt": "say yes", "gold": "yes"},
        ]},
        "evolve": {"rounds": 9},
    }))

    def boom(*args, **kwargs):
        raise AssertionError("snapshot eval must not call evolve")

    monkeypatch.setattr("agentdescent.evolution.evolve", boom)
    assert main(["--json", "snapshot", "eval", str(source), "--spec", str(dest)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is True
    assert report["searched"] is False
    assert report["n"] == 1
    assert report["reward"] == 1.0

    target = tmp_path / "installed"
    assert main(["--json", "snapshot", "apply", str(source), "--to", str(target),
                 "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is not False
    assert not target.exists() or not any(target.iterdir())
    assert main(["--json", "snapshot", "apply", str(source), "--to", str(target)]) == 0
    assert (target / "SKILL.md").read_text() == "always say yes\n"
    assert (target / "tests/n.txt").read_text() == "frozen\n"
