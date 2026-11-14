"""`capability init` finishes its traces fixture durably, or not at all (#1046).

Three shapes, measured at main: an interrupt during the demo write leaves a
partial ``capability-traces.jsonl`` behind, the file is never flushed/fsynced
before it becomes final, and ``--out`` naming an existing directory exits 2
with the traces fixture already landed in the parent of ``--out``.

The fixture is a file the writer owns, so a half one is never a legal state:
either the four demo lines are on disk (fsynced, then renamed into place) or
nothing at that leaf is.
"""
import json
import os

import pytest

from agentdescent import cli
from agentdescent import surface_capability as surface


def _staged(directory):
    return sorted(str(p) for p in directory.glob(".staging-*"))


def test_an_interrupt_while_writing_leaves_no_traces_fixture(tmp_path, monkeypatch):
    spec = tmp_path / "capability.json"
    traces = tmp_path / "capability-traces.jsonl"
    calls = {"n": 0}
    real = surface.json_line

    def interrupted(payload):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(payload)

    monkeypatch.setattr(surface, "json_line", interrupted)
    with pytest.raises(KeyboardInterrupt):
        surface.capability_init(str(spec), demo=True)

    assert calls["n"] == 3
    assert not traces.exists(), "an interrupted write left a partial fixture"
    assert _staged(tmp_path) == [], "an interrupted write left a staging file"


def test_the_traces_are_fsynced_before_they_are_renamed_into_place(
        tmp_path, monkeypatch):
    spec = tmp_path / "capability.json"
    traces = tmp_path / "capability-traces.jsonl"
    events = []

    real_fsync = os.fsync
    real_replace = os.replace

    def recording_fsync(fd):
        try:
            path = os.readlink("/proc/self/fd/%d" % fd)
        except OSError:  # pragma: no cover - /proc is present on the CI hosts
            path = "<unknown>"
        events.append(("fsync", path))
        return real_fsync(fd)

    def recording_replace(source, target, *args, **kwargs):
        events.append(("replace", os.fspath(target)))
        return real_replace(source, target, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    monkeypatch.setattr(os, "replace", recording_replace)
    surface.capability_init(str(spec), demo=True)

    renamed = [i for i, (kind, path) in enumerate(events)
               if kind == "replace" and path == str(traces)]
    assert renamed, "the traces fixture was not renamed into place"
    synced = [i for i, (kind, path) in enumerate(events)
              if kind == "fsync" and path != "<unknown>"
              and os.path.dirname(path) == str(tmp_path)
              and path.endswith(".jsonl")]
    assert synced, "the traces fixture was renamed without an fsync first"
    assert synced[0] < renamed[0], (
        "the traces were renamed into place before they were fsynced")


def test_an_existing_directory_at_out_writes_nothing_outside_it(tmp_path, capsys):
    target = tmp_path / "out"
    target.mkdir()

    assert cli.main(["capability", "init", "--out", str(target), "--demo",
                     "--json"]) == 2

    assert sorted(p.name for p in tmp_path.iterdir()) == ["out"], (
        "a refused --out left a fixture beside it")
    assert list(target.iterdir()) == []


def test_a_plain_demo_writes_both_leaves_and_leaves_no_staging_file(
        tmp_path, capsys):
    spec = tmp_path / "capability.json"

    assert cli.main(["capability", "init", "--out", str(spec), "--demo",
                     "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["ok"] is True
    assert payload["spec"] == str(spec)
    assert payload["traces"] == str(tmp_path / "capability-traces.jsonl")
    lines = (tmp_path / "capability-traces.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert json.loads(lines[0])["trace_id"] == "demo-trace-0"
    assert _staged(tmp_path) == []
