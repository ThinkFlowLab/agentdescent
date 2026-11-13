"""The skill-library seed refuses an unwritable target in one line (#1003).

`#990`/`#995` wrapped the `init` / `apply` artifact writers, but the starters
seeded by `ensure_skill_library_tree` still wrote raw, and the seed ran *before*
the wrapped `--out` writer: an unwritable target traced back, and a refused
`--out` left the seeded `*/SKILL.md` behind. Offline, no model, no port; the
structural cases fail on any uid, so a root CI leg cannot turn them into a
silent pass.
"""

from __future__ import annotations

import pytest

from agentdescent import cli

from tests.test_cli_write_error import _assert_refusal, _argv, _blocked

MODES = [pytest.param(False, id="text"), pytest.param(True, id="json")]


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))


def _target(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    return root


def _skill_md(root):
    return sorted(p.parent.name for p in root.glob("*/SKILL.md"))


def _permissions_are_enforced(tmp_path):
    """A root CI leg ignores `0500`, so that case would pass for the wrong reason."""
    probe = tmp_path / "perm-probe"
    probe.mkdir()
    try:
        probe.chmod(0o500)
        try:
            (probe / "x").write_text("x", encoding="utf-8")
        except OSError:
            return True
        return False
    finally:
        probe.chmod(0o700)


@pytest.mark.parametrize("as_json", MODES)
def test_init_seed_into_a_read_only_target_is_one_line(tmp_path, capsys, as_json):
    if not _permissions_are_enforced(tmp_path):
        pytest.skip("this uid ignores directory permissions (root CI leg)")
    target = _target(tmp_path)
    target.chmod(0o500)
    try:
        rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                            "--agent", "cli_agent", "--out", str(tmp_path / "s.json")))
    finally:
        target.chmod(0o700)
    assert rc == 2
    _assert_refusal(capsys, as_json, path=target / "example-alpha")
    assert _skill_md(target) == []


@pytest.mark.parametrize("as_json", MODES)
def test_init_seed_blocked_by_a_regular_file_is_one_line(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    blocker = target / "example-alpha"
    blocker.write_text("not a directory\n", encoding="utf-8")
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=blocker)
    assert _skill_md(target) == [] and not (tmp_path / "s.json").exists()


@pytest.mark.parametrize("as_json", MODES)
def test_algorithms_run_seed_refusal_is_one_line(tmp_path, capsys, as_json):
    target = _target(tmp_path)
    blocker = target / "example-alpha"
    blocker.write_text("not a directory\n", encoding="utf-8")
    rc = cli.main(_argv(as_json, "algorithms", "run", "evoskill", str(target),
                        "--kind", "skill_library", "--out", str(tmp_path / "s.json")))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=blocker)
    assert _skill_md(target) == []


@pytest.mark.parametrize("as_json", MODES)
def test_a_writable_target_with_an_unwritable_out_seeds_nothing(tmp_path, capsys,
                                                               as_json):
    """Criterion 3: the `--out` refusal is checked before the seed writes."""
    target = _target(tmp_path)
    out = _blocked(tmp_path) / "spec.json"
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(out)))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=out)
    assert sorted(p.name for p in target.iterdir()) == []


@pytest.mark.parametrize("as_json", MODES)
def test_a_refused_spec_backup_leaves_no_seeded_starters(tmp_path, capsys, as_json):
    """A 250-character spec name makes its `.bak-0` sibling 256, over `NAME_MAX`."""
    target = _target(tmp_path)
    out = tmp_path / ("s" * 250)
    out.write_text('{"stale": true}\n', encoding="utf-8")
    rc = cli.main(_argv(as_json, "init", str(target), "--kind", "skill_library",
                        "--agent", "cli_agent", "--out", str(out),
                        "--model", "echo"))
    assert rc == 2
    _assert_refusal(capsys, as_json, path=out)
    assert sorted(p.name for p in target.iterdir()) == []


def test_a_writable_target_still_seeds_both_starters(tmp_path, capsys):
    target = _target(tmp_path)
    assert cli.main(["init", str(target), "--kind", "skill_library",
                     "--agent", "cli_agent", "--out", str(tmp_path / "s.json")]) == 0
    assert _skill_md(target) == ["example-alpha", "example-beta"]
    assert "seeded" in capsys.readouterr().out
