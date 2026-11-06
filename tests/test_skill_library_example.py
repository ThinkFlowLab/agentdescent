"""`examples/skill_library_evolution.py` — the flagship skill-*library* demo.

Offline and seconds-long: run the loop. The claim is that a multi-file library
under ``layout="skill_library"`` is what moved the score — the agent reads
``*/SKILL.md`` off disk, and a missing or wrong skill scores 0.
"""

from __future__ import annotations

import os
import socket
import urllib.request

import pytest

from examples.skill_library_evolution import (
    SKILL_NAMES,
    estimate_calls,
    evolve_library,
    library_validator,
    make_library_dir,
    make_rows,
    offline_agent,
    offline_reflector,
    to_tasks,
)

from agentdescent import load_tree
from agentdescent.skillspec import parse_skill_frontmatter


def _run(**kwargs):
    path = make_library_dir()
    result = evolve_library(
        path, to_tasks(make_rows(16)), agent=offline_agent(),
        reflect_with=offline_reflector(),
        rounds=4, n_workers=2, max_concurrency=1, **kwargs)
    return path, result


def test_seed_library_has_two_valid_agent_skills():
    path = make_library_dir()
    tree = load_tree(path)
    for name in SKILL_NAMES:
        assert f"{name}/SKILL.md" in tree
        fm = parse_skill_frontmatter(tree[f"{name}/SKILL.md"])
        assert fm is not None
        assert fm["name"] == name
        assert fm["description"].strip()
    assert library_validator(tree) is None


def test_the_example_fixes_both_wrong_rules():
    path, result = _run()
    assert result.error is None, result.error
    assert result.final_reward == 1.0
    assert "COLUMN: amount" in result.state["csv-total/references/rules.md"]
    assert "FIELD: year" in result.state["date-parse/references/rules.md"]
    assert result.outcomes().get("committed", 0) >= 1


def test_the_library_is_what_moved_the_score_not_the_agent():
    path = make_library_dir()
    tasks = to_tasks(make_rows(16))
    before = evolve_library(
        path, tasks, agent=offline_agent(), reflect_with=lambda p: "",
        rounds=1, n_workers=1, max_concurrency=1)
    assert before.final_reward == 0.0

    _, after = _run()
    assert after.final_reward == 1.0


def test_missing_skill_files_score_zero():
    """If the agent cannot read skills off disk, reward stays at floor."""
    path = make_library_dir()
    # Wipe rules so the offline agent hits MISSING_SKILL / wrong defaults.
    for name in SKILL_NAMES:
        os.remove(os.path.join(path, name, "references", "rules.md"))
    result = evolve_library(
        path, to_tasks(make_rows(12)), agent=offline_agent(),
        reflect_with=lambda p: "", rounds=1, n_workers=1, max_concurrency=1)
    assert result.final_reward == 0.0


def test_the_run_never_writes_to_the_source_library():
    path, result = _run()
    src = load_tree(path)
    assert src["csv-total/references/rules.md"].strip() == "COLUMN: id"
    assert src["date-parse/references/rules.md"].strip() == "FIELD: month"


def test_write_to_installs_at_least_two_skills():
    path, result = _run()
    plan = result.write_to(path)
    assert plan["backup"]
    installed = load_tree(path)
    assert "COLUMN: amount" in installed["csv-total/references/rules.md"]
    assert "FIELD: year" in installed["date-parse/references/rules.md"]
    skill_dirs = {p.split("/", 1)[0] for p in installed if "/" in p}
    assert skill_dirs >= set(SKILL_NAMES)


def test_estimate_calls_scales():
    assert estimate_calls(4, 2, 16)["agent_rollouts_upper"] > \
        estimate_calls(2, 2, 16)["agent_rollouts_upper"]


def test_dry_run_main_touches_no_network(monkeypatch, capsys):
    """``--dry-run`` prints the library tree + estimate and opens no sockets."""
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("dry-run must not use the network")))
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("dry-run must not open sockets")))

    from examples.skill_library_evolution import main
    monkeypatch.setattr("sys.argv", ["skill_library_evolution", "--dry-run"])
    main()
    out = capsys.readouterr().out
    assert "Library tree:" in out
    assert "csv-total/SKILL.md" in out
    assert "date-parse/SKILL.md" in out
    assert "[dry-run]" in out
