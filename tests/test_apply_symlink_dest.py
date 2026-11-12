"""A link planted in the *destination* is refused, never dereferenced (#977).

`apply` refused links in the source and then handed the destination to
`shutil.copy2` / `open`, both of which follow a link. A link planted in `--to`
therefore redirected both the `.bak-N` copy and the write itself: probe
`skills/SKILL.md -> id_rsa` overwrote the target and left
`skills/SKILL.md.bak-0` holding the target's bytes inside a directory host
scanners read. The guard belongs on the destination, and the containment rule
is `filetree.materialize`'s, not a second copy of it.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import cli
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import TreeError, canonical


def _artifact(tmp_path, files):
    root = tmp_path / "artifact"
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return str(root)


def _leaked_backups(tmp_path, secret: bytes, home: str):
    """Every `.bak-N` (file or inside a backup tree) holding ``secret``.

    A backup that keeps the link instead of the bytes still exposes them to
    anything that reads it, so a link there counts as a leak too.
    """
    hits = []
    for root in (str(tmp_path), home):
        for dirpath, _dirnames, filenames in os.walk(root):
            in_bak = any("bak-" in part for part in dirpath.split(os.sep))
            for name in filenames:
                full = os.path.join(dirpath, name)
                if not (in_bak or ".bak-" in name):
                    continue
                try:
                    if os.path.islink(full):
                        hits.append(full + " -> link")
                    elif open(full, "rb").read() == secret:
                        hits.append(full)
                except OSError:
                    continue
    return hits


def test_a_planted_directory_link_in_the_destination_is_refused(tmp_path, capsys,
                                                                monkeypatch):
    home = str(tmp_path / "ad-home")
    monkeypatch.setenv("AGENTDESCENT_HOME", home)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("outside bytes\n", encoding="utf-8")
    src = _artifact(tmp_path, {"skills/SKILL.md": "evolved\n"})
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink(str(outside), str(dest / "skills"))

    assert cli.main(["apply", "--from", src, "--to", str(dest)]) == 2
    err = capsys.readouterr().err
    assert "symlink" in err and str(dest) in err
    assert (outside / "SKILL.md").read_text(encoding="utf-8") == "outside bytes\n"
    assert sorted(os.listdir(outside)) == ["SKILL.md"]
    assert not _leaked_backups(tmp_path, b"outside bytes\n", home)
    assert os.path.islink(str(dest / "skills"))


def test_a_planted_file_link_at_the_destination_leaf_is_refused(tmp_path, capsys,
                                                                monkeypatch):
    home = str(tmp_path / "ad-home")
    monkeypatch.setenv("AGENTDESCENT_HOME", home)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    src = _artifact(tmp_path, {"rules.md": "evolved\n"})
    dest = tmp_path / "rules.md"
    os.symlink(str(outside), str(dest))

    assert cli.main(["apply", "--from", os.path.join(src, "rules.md"),
                     "--to", str(dest)]) == 2
    err = capsys.readouterr().err
    assert "symlink" in err and str(dest) in err
    assert outside.read_text(encoding="utf-8") == "secret\n"
    # No `.bak-N` may hold the bytes it reached through the link.
    assert not _leaked_backups(tmp_path, b"secret\n", home)
    assert os.path.islink(str(dest))


def test_a_tree_file_link_pointing_outside_the_destination_is_refused(
        tmp_path, capsys, monkeypatch):
    home = str(tmp_path / "ad-home")
    monkeypatch.setenv("AGENTDESCENT_HOME", home)
    outside = tmp_path / "id_rsa"
    outside.write_text("PRIVATE KEY\n", encoding="utf-8")
    src = _artifact(tmp_path, {"skills/SKILL.md": "evolved\n"})
    dest = tmp_path / "dest"
    (dest / "skills").mkdir(parents=True)
    os.symlink(str(outside), str(dest / "skills" / "SKILL.md"))

    assert cli.main(["apply", "--from", src, "--to", str(dest)]) == 2
    err = capsys.readouterr().err
    assert "symlink" in err
    assert outside.read_text(encoding="utf-8") == "PRIVATE KEY\n"
    assert not _leaked_backups(tmp_path, b"PRIVATE KEY\n", home)


def test_apply_of_a_run_refuses_a_planted_destination_link(tmp_path):
    """The run-id path writes through `filetree.materialize`; same refusal."""
    outside = tmp_path / "id_rsa"
    outside.write_text("PRIVATE KEY\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    os.symlink(str(outside), str(dest / "SKILL.md"))
    result = EvolutionResult(state={"SKILL.md": "evolved\n"},
                             rendered=canonical({"SKILL.md": "evolved\n"}),
                             final_reward=0.0, history=[], ledger_log=[])
    with pytest.raises(TreeError, match="symlink"):
        result.write_to(str(dest))
    assert outside.read_text(encoding="utf-8") == "PRIVATE KEY\n"
