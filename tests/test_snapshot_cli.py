"""CLI surface for portable snapshots: show, eval, apply — no search."""

import json
import os
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

    # Text apply writes `rendered` as one file (#1149). The previous rows
    # pinned a hybrid: kind=text but materialising SKILL.md / tests/n.txt
    # into a directory, which no real text run produces.
    dest = tmp_path / "missing.txt"
    assert main(["--json", "snapshot", "apply", str(source), "--to", str(dest),
                 "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is not False
    assert payload["noop"] is False
    assert not dest.exists()
    assert main(["--json", "snapshot", "apply", str(source), "--to", str(dest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is False
    assert payload["written"] == [os.path.abspath(str(dest))]
    assert dest.read_text(encoding="utf-8") == "always say yes"

    assert main(["--json", "snapshot", "apply", str(source), "--to", str(dest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is True
    assert payload["written"] == []
    assert dest.read_text(encoding="utf-8") == "always say yes"

    as_dir = tmp_path / "as-dir"
    as_dir.mkdir()
    rc = main(["--json", "snapshot", "apply", str(source), "--to", str(as_dir)])
    err = json.loads(capsys.readouterr().out)
    assert rc == 2 and err["ok"] is False
    assert "is a directory" in err["error"] and "--to FILE" in err["error"]
    assert list(as_dir.iterdir()) == []

    # An empty-rules text snapshot still applies the seed prompt (render()),
    # not a no-op with written: [].
    empty = ArtifactSnapshot(
        artifact_id="seed.txt", files={}, editable=["**"], frozen=[],
        kind="text", version=1, id="seed.txt@v1",
        rendered="You are a terse assistant.\n")
    empty_src = tmp_path / "empty.json"
    empty.save(empty_src)
    seed_dest = tmp_path / "prompt.txt"
    assert main(["--json", "snapshot", "apply", str(empty_src),
                 "--to", str(seed_dest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is False
    assert payload["written"] == [os.path.abspath(str(seed_dest))]
    assert seed_dest.read_text(encoding="utf-8") == "You are a terse assistant.\n"

    # Tree kinds keep today's materialise behaviour.
    tree = ArtifactSnapshot.from_filetree(
        FileTree({"SKILL.md": "always say yes\n", "tests/n.txt": "frozen\n"},
                 frozen=["tests/**"]),
        artifact_id="skill", kind="skill_dir",
        lineage={"version": 2, "id": "skill@v2", "parent": "skill@v1",
                 "root": "skill@v1"})
    tree_source = tmp_path / "skill-tree.json"
    tree.save(tree_source)
    target = tmp_path / "installed"
    assert main(["--json", "snapshot", "apply", str(tree_source), "--to", str(target),
                 "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is not False
    assert not target.exists() or not any(target.iterdir())
    assert main(["--json", "snapshot", "apply", str(tree_source), "--to", str(target)]) == 0
    assert (target / "SKILL.md").read_text() == "always say yes\n"
    assert (target / "tests/n.txt").read_text() == "frozen\n"
