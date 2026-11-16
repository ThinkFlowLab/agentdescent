"""A default spec must never land inside a directory target (#1122).

``algorithm_spec``'s description promises the spec is written under
``$AGENTDESCENT_HOME`` / the operator's write allowlist, "never inside a
directory target". After #1108 the default root is chosen *from* the
allowlist, and the promise is false in one reachable case: when the chosen
root is the directory target itself, or inside it, the spec is written into
the target. The file still sits inside the allowlist, so this is a lost
property and a false promise rather than an escape -- but a spec dropped in
the target becomes target content for later plans.
"""

import json
import os

import pytest

from agentdescent.mcp import TOOL_DESCRIPTIONS, Tools

_FLAGS = dict(model="deepseek-v4-flash",
              base_url="https://ark.cn-beijing.volces.com/api/coding/v3")


def _cases(tmp_path, n=8):
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(n)))
    return cases


def _target(tmp_path):
    """A skill_dir target: this is the kind whose ``path`` is a directory."""
    target = tmp_path / "target"
    (target / "sub").mkdir(parents=True)
    (target / "SKILL.md").write_text("be terse\n")
    return target


@pytest.fixture
def host_cli(tmp_path, monkeypatch):
    """A ``claude`` on PATH: a directory-kind spec names ``claude_code``.

    ``algorithm_spec`` plans before it returns, and plan hard-refuses a spec
    whose agent CLI is not installed (#346). CI installs no agent CLI, so the
    two rows below -- which assert a *usable* default, not just the refusal --
    failed there on ``ok is False`` even though the spec was written at the
    right outside-the-target path. The stub keeps the row host-independent
    without touching what it asserts (#1122 CI).
    """
    binary = tmp_path / "bin" / "claude"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    monkeypatch.setenv(
        "PATH", str(binary.parent) + os.pathsep + os.environ.get("PATH", ""))
    return binary


def test_only_inside_the_target_roots_are_refused(tmp_path):
    """Every allowed root is the target or inside it: refuse, do not write.

    The refusal names both facts -- the directory target and that the roots
    the operator allows are all inside it -- because a host cannot act on
    "no write directory is allowed".
    """
    target = _target(tmp_path)
    cases = _cases(tmp_path)

    result = Tools(None, surface_write_dirs=(str(target),)).algorithm_spec(
        "archive_selection", str(target), kind="skill_dir", cases=str(cases),
        **_FLAGS)

    assert result["ok"] is False, result
    error = result["error"]
    assert str(target) in error
    assert "inside" in error
    assert "AGENTDESCENT_SURFACE_WRITE_DIRS" in error
    assert "spec_path" not in result
    # Nothing was written into the target: not the default name, not any file.
    assert list(target.rglob("agentdescent.*.spec.json")) == []


def test_a_root_inside_the_target_is_refused_too(tmp_path):
    """A root *below* the target is still inside it (#1122's third repro)."""
    target = _target(tmp_path)
    cases = _cases(tmp_path)

    result = Tools(None, surface_write_dirs=(str(target / "sub"),)).algorithm_spec(
        "archive_selection", str(target), kind="skill_dir", cases=str(cases),
        **_FLAGS)

    assert result["ok"] is False, result
    assert "inside" in result["error"]
    assert list(target.rglob("agentdescent.*.spec.json")) == []


def test_a_directory_target_that_is_the_home_falls_back_to_the_cwd(
        tmp_path, monkeypatch, host_cli):
    """Target == ``$AGENTDESCENT_HOME`` with the allowlist unset (#1122).

    The default allowlist is the server's cwd plus the home, so the cwd is
    still a usable root and the spec goes there, outside the target.
    """
    server = tmp_path / "server"
    server.mkdir()
    target = _target(tmp_path)
    cases = _cases(tmp_path)
    monkeypatch.chdir(server)
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)
    monkeypatch.setenv("AGENTDESCENT_HOME", str(target))

    result = Tools(None).algorithm_spec(
        "archive_selection", str(target), kind="skill_dir", cases=str(cases),
        **_FLAGS)

    assert result["ok"] is True, result
    assert result["spec_path"] == str(server / "agentdescent.archive_selection.spec.json")
    assert list(target.rglob("agentdescent.*.spec.json")) == []


def test_a_usable_root_outside_the_target_wins(tmp_path, host_cli):
    """The first allowed root is inside the target; the next one is not."""
    target = _target(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    cases = _cases(tmp_path)

    result = Tools(None, surface_write_dirs=(
        str(target / "sub"), str(allowed))).algorithm_spec(
            "archive_selection", str(target), kind="skill_dir",
            cases=str(cases), **_FLAGS)

    assert result["ok"] is True, result
    assert result["spec_path"] == str(allowed / "agentdescent.archive_selection.spec.json")
    assert list(target.rglob("agentdescent.*.spec.json")) == []


def test_the_description_still_promises_no_spec_inside_a_directory_target():
    text = TOOL_DESCRIPTIONS["algorithm_spec"]

    assert "never inside" in text
    assert "directory target" in text
