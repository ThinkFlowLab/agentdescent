"""The CLI obeys ``AGENTDESCENT_SURFACE_WRITE_DIRS`` on its write paths (#1082).

The MCP surface refused a write outside the operator's allowlist (#1018), but
`agentdescent apply` passed no check, so a host worker that could not write
through the tool could still write through the CLI. Enforcement is opt-in,
like the rest of the variable: unset leaves the CLI as it was, and an empty
value refuses every write -- the reading the MCP surface gives it.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import cli


def _artifact(tmp_path) -> "os.PathLike[str]":
    source = tmp_path / "artifact"
    source.mkdir()
    (source / "rules.md").write_text("evolved\n", encoding="utf-8")
    return source


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))


@pytest.mark.parametrize("dry_run", [False, True])
def test_apply_refuses_a_destination_outside_the_write_dirs(
        tmp_path, monkeypatch, capsys, dry_run):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(allowed))
    dest = tmp_path / "outside"
    argv = ["apply", "--from", str(_artifact(tmp_path)), "--to", str(dest)]
    if dry_run:
        argv += ["--dry-run", "--json"]

    assert cli.main(argv) == 2

    captured = capsys.readouterr()
    if dry_run:
        assert "write allowlist" in json.loads(captured.out)["error"]
    else:
        assert "write allowlist" in captured.err
    assert not dest.exists()


def test_an_empty_value_refuses_every_write(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", "")
    dest = tmp_path / "anywhere"

    assert cli.main(["apply", "--from", str(_artifact(tmp_path)), "--to", str(dest)]) == 2

    assert "write allowlist" in capsys.readouterr().err
    assert not dest.exists()


def test_apply_inside_the_write_dirs_still_writes(tmp_path, monkeypatch, capsys):
    allowed = tmp_path / "allowed"
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(allowed))
    dest = allowed / "written"

    assert cli.main(["apply", "--from", str(_artifact(tmp_path)), "--to", str(dest)]) == 0

    assert (dest / "rules.md").read_text(encoding="utf-8") == "evolved\n"


def test_unset_means_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)
    dest = tmp_path / "unconstrained"

    assert cli.main(["apply", "--from", str(_artifact(tmp_path)), "--to", str(dest)]) == 0

    assert (dest / "rules.md").read_text(encoding="utf-8") == "evolved\n"


def test_show_refuses_to_plan_a_write_outside_the_write_dirs(tmp_path, monkeypatch, capsys):
    """`show --diff` must not advertise a plan the host is not allowed to apply."""
    from tests.test_skill_library_apply_install import _make_library_run

    store, run_id = _make_library_run(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(allowed))

    assert cli.main(["--store", store, "show", run_id, "--diff", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "write allowlist" in payload["apply_plan"]["error"]
    # `show` never writes; the refusal is in the plan it advertises.
    assert not (allowed / "seed-lib").exists()
