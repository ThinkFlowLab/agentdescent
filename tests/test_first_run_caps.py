"""The first-run surfaces name the probe and the per-call cap (#1201).

#1166 / #1184 added the per-call cap (`agentdescent evolve --max-calls` /
`--max-usd`), and `docs/start.md` documents it. The surfaces a new user or host
agent actually follows did not name it: the shared host skill, the
plugin-quickstart habits, the budget paragraph in `docs/plugins.md`, and the
`next:` line `algorithms run` / `demo --algorithm` print. A first real run is
started from those lines, so the preflight and the cap have to be readable
there, together with the `--budget` overshoot warning they do not replace.

The rendered plugin copies are not compared here: `tests/test_integrations.py`
re-renders and diffs them already, and these rows only pin the words a reader
sees.
"""

import io
import json
import os
import re
from contextlib import redirect_stdout

import pytest

from agentdescent import cli
from agentdescent.integrations import ALGORITHMS_COMMAND, EVOLVE_COMMAND, skill_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALGORITHMS = ("gepa", "archive_selection")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def _run(argv):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(argv)
    return code, buf.getvalue()


def _prompt_and_cases(tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Answer the question.\n", encoding="utf-8")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(4)),
        encoding="utf-8")
    return prompt, cases


def test_shared_host_skill_names_the_per_call_cap():
    text = skill_text()
    assert "--max-calls" in text
    assert "--max-usd" in text
    assert "--probe" in text            # the preflight stays the first step


def test_slash_commands_name_the_probe_and_the_cap():
    """#1228: /evolve and /algorithms run must name the same first-run
    preflight and per-call cap as SKILL.md / the CLI next: line."""
    for text in (EVOLVE_COMMAND, ALGORITHMS_COMMAND):
        assert "probe" in text
        assert "max_calls" in text or "--max-calls" in text
    run_branch = ALGORITHMS_COMMAND.split("**`run", 1)[1]
    assert "probe" in run_branch
    assert "--max-calls" in run_branch
    assert "max_calls" in run_branch
    # The run branch must not still tell the host to start from
    # algorithm_spec / a bare algorithms run with no cap.
    assert "then `evolve` after yes" not in run_branch


def test_plugin_quickstart_habits_name_the_per_call_cap():
    text = _read("docs", "plugin-quickstart.md")
    assert "--max-calls" in text
    assert "--max-usd" in text
    assert "overshoot" in text          # the weaker cap keeps its warning


def test_plugins_budget_paragraph_names_the_per_call_cap():
    text = _read("docs", "plugins.md")
    budget = text.split("A dollar budget", 1)[1].split("\n## ", 1)[0]
    assert "--max-calls" in budget
    assert "overshoot" in budget


@pytest.mark.parametrize("name", ALGORITHMS)
def test_algorithms_run_next_names_the_probe_then_the_cap(tmp_path, monkeypatch, name):
    monkeypatch.chdir(tmp_path)
    prompt, cases = _prompt_and_cases(tmp_path)
    out = tmp_path / f"{name}.spec.json"
    code, text = _run([
        "algorithms", "run", name, str(prompt), str(cases),
        "--model", "m", "--base-url", "https://example.test/v1",
        "--rounds", "1", "--workers", "1", "--out", str(out),
    ])
    assert code == 0, text
    nxt = [line for line in text.splitlines() if line.startswith("next:")]
    assert nxt, text
    line = nxt[-1]
    assert "plan" in line and "--probe" in line
    # The cap is the plan's own upper bound, not a placeholder.
    bound = re.search(r"up to (\d+) agent calls", text)
    assert bound, text
    assert f"--max-calls {bound.group(1)}" in line

    code, text = _run([
        "--json", "algorithms", "run", name, str(prompt), str(cases),
        "--model", "m", "--base-url", "https://example.test/v1",
        "--rounds", "1", "--workers", "1", "--out", str(out),
    ])
    assert code == 0, text
    payload = json.loads(text)
    assert "--probe" in payload["next"]
    assert f"--max-calls {bound.group(1)}" in payload["next"]


@pytest.mark.parametrize("name", ALGORITHMS)
def test_demo_algorithm_footer_names_the_probe_then_the_cap(tmp_path, monkeypatch, name):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    code, text = _run(["--store", str(tmp_path / "runs"), "demo",
                       "--dir", str(tmp_path / "work"), "--algorithm", name])
    assert code == 0, text
    assert f"agentdescent algorithms run {name} " in text
    assert "--out spec.json" in text
    assert "agentdescent plan spec.json --probe" in text
    assert "agentdescent evolve spec.json --max-calls <N>" in text
    assert "agentdescent doctor" in text

    code, text = _run(["--store", str(tmp_path / "runs2"), "demo",
                       "--dir", str(tmp_path / "work2"), "--algorithm", name,
                       "--json"])
    assert code == 0, text
    steps = json.loads(text)["next"]
    assert "agentdescent plan spec.json --probe" in steps
    assert "agentdescent evolve spec.json --max-calls <N>" in steps

def test_default_demo_footer_names_the_probe_then_the_cap(tmp_path, monkeypatch):
    # #1217: the README path (`demo`, then "your own run") had the same
    # gap #1201 closed for `demo --algorithm` / `algorithms run`.
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    code, text = _run(["--store", str(tmp_path / "runs"), "demo",
                       "--dir", str(tmp_path / "work")])
    assert code == 0, text
    assert "agentdescent plan spec.json --probe" in text
    assert "agentdescent evolve spec.json --max-calls <N>" in text
    assert "--out spec.json" in text
    assert "agentdescent doctor" in text

    code, text = _run(["--store", str(tmp_path / "runs2"), "demo",
                       "--dir", str(tmp_path / "work2"), "--json"])
    assert code == 0, text
    steps = json.loads(text)["next"]
    assert "agentdescent plan spec.json --probe" in steps
    assert "agentdescent evolve spec.json --max-calls <N>" in steps


def test_demo_kind_skill_library_footer_names_the_probe_then_the_cap(
        tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    code, text = _run(["--store", str(tmp_path / "runs"), "demo",
                       "--kind", "skill_library",
                       "--dir", str(tmp_path / "work"), "--json"])
    assert code == 0, text
    steps = json.loads(text)["next"]
    assert "agentdescent plan spec.json --probe" in steps
    assert "agentdescent evolve spec.json --max-calls <N>" in steps
    assert any("--kind skill_library" in s for s in steps)


def test_bare_plan_next_names_the_probe_then_the_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prompt, cases = _prompt_and_cases(tmp_path)
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "kind": "text", "target": str(prompt),
        "data": {"path": str(cases)}, "score": "contains",
        "agent": "echo", "reflect": "echo",
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    }), encoding="utf-8")

    code, text = _run(["plan", str(spec)])
    assert code == 0, text
    nxt = [line for line in text.splitlines() if line.startswith("next:")]
    assert nxt, text
    line = nxt[-1]
    assert "plan" in line and "--probe" in line
    bound = re.search(r"up to (\d+) agent calls", text)
    assert bound, text
    assert f"--max-calls {bound.group(1)}" in line

    code, text = _run(["--json", "plan", str(spec)])
    assert code == 0, text
    payload = json.loads(text)
    assert payload["next"] == (
        f"agentdescent plan {spec} --probe, then "
        f"agentdescent evolve {spec} --max-calls {bound.group(1)}")
    assert "ready" not in payload and "probe" not in payload

def _first_init_my_skill_block(text):
    """The first fenced command block that contains the README-style init line."""
    parts = text.split("```")
    for i, part in enumerate(parts):
        if "init ./my-skill" in part:
            body = part
            if body.startswith("bash"):
                body = body.split("\n", 1)[1]
            return body
    raise AssertionError("no init ./my-skill command block")


def _section_after(text, heading):
    assert heading in text, heading
    return text.split(heading, 1)[1]


def test_readme_quickstart_names_the_probe_and_the_cap():
    # #1232: the README "your own run" block still started uncapped after #1229.
    block = _first_init_my_skill_block(_read("README.md"))
    assert "plan spec.json --probe" in block
    assert "evolve spec.json --max-calls" in block


def test_start_page_opening_cli_block_names_the_probe_and_the_cap():
    # The later --probe / --max-calls sections on this page do not count:
    # the opening CLI path is what a new user copies.
    opening = _read("docs", "start.md").split("## With a real model", 1)[0]
    block = _first_init_my_skill_block(opening)
    assert "plan spec.json --probe" in block
    assert "evolve spec.json --max-calls" in block


def test_plugin_quickstart_command_block_names_the_cap():
    # Habits paragraphs already named --max-calls; the copied block did not.
    block = _first_init_my_skill_block(_read("docs", "plugin-quickstart.md"))
    assert "plan spec.json --probe" in block
    assert "evolve spec.json --max-calls" in block


def test_skill_without_mcp_cheatsheet_names_the_probe_and_the_cap():
    cheat = _section_after(skill_text(), "## Without MCP")
    fence = cheat.split("```", 2)[1]
    assert "--probe" in fence
    assert "--max-calls" in fence
    # The bare evolve line must not remain in this cheatsheet.
    assert "evolve spec.json --detach\n" not in fence


def test_grok_bot_host_md_names_the_probe_and_the_cap():
    from agentdescent.integrations import grok_bot_host_md
    drive = _section_after(grok_bot_host_md(), "Drive AgentDescent")
    drive = drive.split("MCP (optional", 1)[0]
    assert "plan --probe" in drive
    assert "evolve --max-calls" in drive
    assert "evolve the written" not in drive
