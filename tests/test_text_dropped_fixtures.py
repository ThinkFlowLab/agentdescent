"""``kind=text`` names the case ``fixtures`` its prompt never shows (#1251).

``build_tasks`` maps a case's ``fixtures`` column into ``task.meta`` and the
directory runners stage it into the workspace. A text rollout is
``{skill} + {prompt}`` with no workspace, so the body never reaches the model:
the plan said ``ok`` and the run learned nothing. The hint that sends a
``skill_dir`` user down this path named the target but not the trap, so the
two surfaces are pinned together here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentdescent import algorithms, cli


def _skill_dir(tmp_path: Path) -> Path:
    skill = tmp_path / "csv-total"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: csv-total\ndescription: total a column\n---\n"
        "Read data.csv in the working directory and sum its amount column.\n")
    return skill


def _fixture_cases(path: Path, *, n: int = 8, in_prompt: bool = False) -> Path:
    """Skill-dir style cases: the CSV lives in ``fixtures``, not in the prompt."""
    rows = []
    for i in range(n):
        body = f"id,amount\n1,{i + 1}\n2,{i + 2}\n"
        prompt = "What is the total?"
        if in_prompt:
            prompt = f"What is the total?\n```csv\n{body}```"
        rows.append({"prompt": prompt, "gold": str(2 * i + 3),
                     "fixtures": {"data.csv": body}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


def _run_ace_on_the_file(tmp_path: Path, cases: Path, capsys) -> str:
    out = tmp_path / "ace.spec.json"
    assert cli.main([
        "algorithms", "run", "ace",
        str(_skill_dir(tmp_path) / "SKILL.md"), str(cases),
        "--kind", "text", "--model", "m",
        "--base-url", "https://example.test/v1", "--out", str(out),
    ]) == 0
    return capsys.readouterr().out


def test_following_the_kind_mismatch_hint_warns_that_fixtures_are_dropped(
        tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases = _fixture_cases(tmp_path / "cases.jsonl")
    printed = _run_ace_on_the_file(tmp_path, cases, capsys)
    assert "note:" in printed
    assert "data.csv" in printed
    assert "inline" in printed
    assert "demo --algorithm ace" in printed


def test_plan_json_carries_the_same_note(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases = _fixture_cases(tmp_path / "cases.jsonl")
    _run_ace_on_the_file(tmp_path, cases, capsys)
    assert cli.main(["plan", str(tmp_path / "ace.spec.json"), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    notes = " ".join(payload["notes"])
    assert "data.csv" in notes and "inline" in notes


def test_the_hint_itself_names_the_fixture_trap(tmp_path):
    skill = _skill_dir(tmp_path)
    msg = algorithms.kind_mismatch_message(
        algorithms.get("ace"), "skill_dir", target=str(skill), via="run")
    assert "target it as text" in msg
    assert "fixtures" in msg
    assert "inline" in msg
    # No `--algorithm` here: the #702 guard keeps that flag out of the run
    # route, and `demo --kind text` writes the same CSV-inlined cases.
    assert "demo --kind text" in msg
    assert "--algorithm" not in msg


def test_a_fixture_body_already_in_the_prompt_is_not_reported(
        tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases = _fixture_cases(tmp_path / "cases.jsonl", in_prompt=True)
    printed = _run_ace_on_the_file(tmp_path, cases, capsys)
    assert "data.csv" not in printed
    assert "inline" not in printed


def test_fixture_free_text_cases_stay_quiet(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(8)))
    printed = _run_ace_on_the_file(tmp_path, cases, capsys)
    assert "data.csv" not in printed
    assert "inline" not in printed


def test_the_demo_path_still_inlines_the_csv(tmp_path):
    """The repair the note names is the one the demo already does."""
    from agentdescent import demo

    assert "```csv" in demo._text_rows(n=1)[0]["prompt"]
    assert "fixtures" not in demo._text_rows(n=1)[0]
    assert demo.OFFLINE_TEXT_ALGORITHMS
