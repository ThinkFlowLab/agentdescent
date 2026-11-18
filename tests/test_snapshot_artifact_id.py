"""`artifact_id` is an identifier, never a path component (#1150).

A snapshot JSON can come from someone else, and both staging writes used to
derive their path from it: `os.path.join` lets an absolute id replace the
tempdir and a ``../`` chain walk out of it, so a victim applying or scoring
a snapshot JSON received from someone else could make the staging write
land outside the tempdir. The id is now validated as one path-safe
component at construction, and staging uses a fixed name so a regression
at either end alone cannot re-open the write.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from agentdescent.artifact_snapshot import ArtifactSnapshot, _write_target
from agentdescent.cli import main

UNSAFE_IDS = [
    "/tmp/evil",                       # absolute replaces the tempdir
    "C:/evil", "C:\\evil",             # drive-letter forms
    "../escaped.txt",                   # walks out of the tempdir
    "..", ".",                          # the tempdir itself
    "a/b", "a\\b",                      # separators inside
    "evil\x00",                         # NUL
]


def _payload(artifact_id: str) -> dict:
    return {
        "format": "agentdescent.artifact_snapshot",
        "format_version": 1,
        "artifact_id": artifact_id,
        "kind": "text",
        "files": {"skill": "say yes"},
        "rendered": "say yes",
    }


def _snapshot_file(path: Path, artifact_id: str) -> Path:
    path.write_text(json.dumps(_payload(artifact_id)))
    return path


def _dest_spec(path: Path) -> Path:
    path.write_text(json.dumps({
        "kind": "text", "target": "ignored",
        "agent": "echo", "score": "contains",
        "data": {"inline": [
            {"id": "a", "prompt": "say yes", "gold": "yes"},
        ]},
    }))
    return path


@pytest.mark.parametrize("artifact_id", UNSAFE_IDS)
def test_an_artifact_id_that_is_not_one_component_is_refused(artifact_id):
    with pytest.raises(ValueError, match="artifact_id"):
        ArtifactSnapshot(artifact_id=artifact_id, files={"skill": "x"})


@pytest.mark.parametrize("artifact_id", UNSAFE_IDS)
def test_from_dict_refuses_the_same_ids_from_a_snapshot_json(artifact_id):
    with pytest.raises(ValueError, match="artifact_id"):
        ArtifactSnapshot.from_dict(_payload(artifact_id))


@pytest.mark.parametrize("artifact_id", ["skill", "SKILL.md", "seed-prompt"])
def test_a_safe_identifier_still_builds(artifact_id):
    snap = ArtifactSnapshot(artifact_id=artifact_id, files={"skill": "x"})
    assert snap.snapshot_id == artifact_id


def test_eval_refuses_an_absolute_artifact_id_and_writes_nothing_there(
        tmp_path, capsys, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / "evil.txt"
    source = _snapshot_file(tmp_path / "evil.json", str(evil))
    dest = _dest_spec(tmp_path / "dest.json")

    def boom(*args, **kwargs):
        raise AssertionError("snapshot eval must not call evolve")

    monkeypatch.setattr("agentdescent.evolution.evolve", boom)
    code = main(["--json", "snapshot", "eval", str(source), "--spec", str(dest)])
    assert code == 2
    assert not evil.exists()
    shown = json.loads(capsys.readouterr().out)
    assert shown["ok"] is False
    assert "artifact_id" in shown["error"]


def test_eval_refuses_a_dotdot_artifact_id_and_writes_nothing_outside(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = _snapshot_file(tmp_path / "evil.json", "../escaped.txt")
    dest = _dest_spec(tmp_path / "dest.json")

    def boom(*args, **kwargs):
        raise AssertionError("snapshot eval must not call evolve")

    monkeypatch.setattr("agentdescent.evolution.evolve", boom)
    code = main(["--json", "snapshot", "eval", str(source), "--spec", str(dest)])
    assert code == 2
    assert not (tmp_path / "escaped.txt").exists()
    shown = json.loads(capsys.readouterr().out)
    assert shown["ok"] is False


def test_apply_refuses_an_absolute_artifact_id_and_writes_nothing_there(
        tmp_path, capsys):
    outside = tmp_path / "outside"
    outside.mkdir()
    source = _snapshot_file(tmp_path / "evil.json", str(outside))
    to = tmp_path / "victim"

    code = main(["--json", "snapshot", "apply", str(source), "--to", str(to),
                 "--dry-run"])
    assert code == 2
    assert not any(outside.iterdir())
    shown = json.loads(capsys.readouterr().out)
    assert shown["ok"] is False
    assert "artifact_id" in shown["error"]


def test_apply_refuses_a_dotdot_artifact_id_and_writes_nothing_outside(
        tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    source = _snapshot_file(tmp_path / "evil.json", "../escaped")
    to = tmp_path / "victim"

    code = main(["--json", "snapshot", "apply", str(source), "--to", str(to),
                 "--dry-run"])
    assert code == 2
    assert not (tmp_path / "escaped").exists()
    shown = json.loads(capsys.readouterr().out)
    assert shown["ok"] is False


def test_write_target_stages_text_under_a_fixed_name(tmp_path):
    snap = ArtifactSnapshot(artifact_id="skill", files={"skill": "say yes"},
                            rendered="say yes")
    path = _write_target(snap, "text", str(tmp_path))
    assert os.path.basename(path) == "artifact.txt"
    assert Path(path).read_text() == "say yes"
    assert not (tmp_path / "skill").exists()


def test_write_target_stages_a_tree_under_a_fixed_name(tmp_path):
    snap = ArtifactSnapshot(artifact_id="skill", files={"SKILL.md": "x"})
    dest = _write_target(snap, "skill_dir", str(tmp_path))
    assert os.path.basename(dest) == "artifact"
    assert (Path(dest) / "SKILL.md").read_text() == "x"
    assert not (tmp_path / "skill").exists()


@pytest.mark.parametrize("kind,files,expected", [
    ("text", {"skill": "say yes"}, "artifact.txt"),
    ("skill_dir", {"SKILL.md": "x"}, "artifact"),
])
def test_apply_stages_under_a_fixed_name_not_the_id(
        tmp_path, capsys, monkeypatch, kind, files, expected):
    captured = {}

    def fake_apply(src, *, to, dry_run, backup, check_write):
        captured["src"] = src
        return {"ok": True, "planned": 1}

    monkeypatch.setattr("agentdescent.cli.apply_from_payload", fake_apply)
    payload = _payload("skill")
    payload["kind"] = kind
    payload["files"] = files
    if kind != "text":
        payload.pop("rendered", None)
    source = tmp_path / "good.json"
    source.write_text(json.dumps(payload))
    code = main(["--json", "snapshot", "apply", str(source),
                 "--to", str(tmp_path / "victim")])
    assert code == 0
    assert os.path.basename(captured["src"]) == expected
    assert not (tmp_path / "victim" / "skill").exists()
