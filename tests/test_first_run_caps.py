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
from agentdescent.integrations import skill_text

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
