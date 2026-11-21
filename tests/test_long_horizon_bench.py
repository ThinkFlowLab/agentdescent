"""The long-horizon bench has to survive a long run and report what went wrong.

Its job is to evolve **one** artifact across sequential steps and publish the
step-by-step record. Three fixtures make that trustworthy:

* the offline ``main(["--steps", "3", "--seeds", "1", "--json"])`` run finishes
  inside five seconds and every step is recorded ``ok``;
* a step that raises is recorded as ``ok: false`` with the exception in it, and
  the run still finishes -- a long loop that dies on step 12 has no evidence;
* two runs of the same inputs share a ``manifest_id``, so the report identifies
  the run rather than the machine.

The rest pin the two ways a forgetting metric can be vacuous: forgetting must be
computed from a curve that really peaked and fell, and the held-out split must
be *reported* rather than assumed -- a gate that cannot see a family is the case
this bench exists to measure.
"""

import json
import time

from bench.long_horizon import (
    FAMILIES,
    append_rule,
    check_tasks,
    main,
    parse_playbook,
    run_bench,
)


def test_the_bench_runs_every_step(capsys):
    started = time.perf_counter()
    code = main(["--steps", "3", "--seeds", "1", "--json"])
    elapsed = time.perf_counter() - started
    assert code == 0
    assert elapsed < 5.0, f"the offline bench took {elapsed:.1f}s"
    out = json.loads(capsys.readouterr().out)

    assert out["bench"] == "long_horizon"
    assert out["all_ok"] is True
    assert out["steps"] == 3
    assert out["seeds"] == [0]
    run = out["runs"][0]
    assert [step["ok"] for step in run["steps"]] == [True, True, True]
    assert len(run["steps"]) == 3
    # every step is either a commit or a refusal, never neither
    assert run["committed"] + run["refused"] == 3
    # the checks the gate could see, named rather than assumed
    assert out["checks"]["holdout"] == 6
    assert out["checks"]["families_without_holdout"] == []
    assert set(out["checks"]["holdout_by_family"]) == set(FAMILIES)
    # retention can never beat the best assignment the domain allows
    assert run["retention"] <= out["checks"]["ceiling"] + 1e-12
    assert run["final_rules"]


def test_a_raising_step_is_recorded_not_raised(capsys):
    code = main(["--steps", "3", "--seeds", "1", "--fail-step", "2", "--json"])
    assert code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["all_ok"] is False
    run = out["runs"][0]
    assert len(run["steps"]) == 3, "the run must finish after a failed step"
    failed = run["steps"][1]
    assert failed["ok"] is False
    assert "injected failure at step 2" in failed["error"]
    # the artifact was left exactly as it was, and the loop carried on
    assert failed["parent_sha"] == failed["child_sha"]
    assert run["steps"][2]["ok"] is True
    assert run["verdict"] == "errored"


def test_two_runs_share_a_manifest_id_and_every_number():
    first = run_bench(seeds=1, steps=3, code_version="test")
    second = run_bench(seeds=1, steps=3, code_version="test")
    assert first["manifest_id"] == second["manifest_id"]
    for report in (first, second):
        report["runs"][0]["cost"].pop("wall_clock_s")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_forgetting_is_measured_from_a_curve_that_really_fell():
    report = run_bench(seeds=1, steps=9, code_version="test")
    run = report["runs"][0]
    assert run["forgetting"] > 0.0
    curves = {task["task_id"]: task for task in run["report"]["tasks"]}
    fell = [task for task in curves.values()
            if task["forgetting"] > 0.0]
    assert fell, "forgetting must come from a per-check curve, not a constant"
    for task in fell:
        valid = [score for score, error in zip(task["scores"], task["errors"])
                 if error is None]
        assert max(valid) > valid[-1]
        assert task["forgetting"] == max(0.0, max(valid) - valid[-1])
    assert run["max_forgetting"] == max(t["forgetting"] for t in curves.values())
    assert run["verdict"] == "forgetting"


def test_a_held_out_split_that_misses_a_family_is_reported():
    report = run_bench(seeds=1, steps=9, holdout_fraction=0.25,
                       code_version="test")
    assert report["checks"]["holdout"] == 4
    assert report["checks"]["families_without_holdout"], (
        "a four-check holdout cannot cover six families; the report must say so")
    run = report["runs"][0]
    # the gate could not see those families, and the loop still lost checks
    assert run["forgetting"] > 0.0
    assert run["verdict"] == "forgetting"


def test_a_refused_step_leaves_the_artifact_alone():
    report = run_bench(seeds=1, steps=9, code_version="test")
    run = report["runs"][0]
    refused = [step for step in run["steps"] if not step["committed"]]
    assert refused, "the gate must refuse something on a conflicted domain"
    for step in refused:
        assert step["ok"] is True
        assert step["parent_sha"] == step["child_sha"]
        assert step["version_before"] == step["version_after"]
        assert step["reason"]
    for step in run["lineage"]:
        assert step["parent_sha"] != step["child_sha"]


def test_a_later_rule_line_overrides_the_earlier_one():
    text = append_rule("# Playbook\n", "add", "sum")
    assert parse_playbook(text) == {"add": "sum"}
    text = append_rule(text, "add", "product")
    # both lines are still in the file; only the last one is in force
    assert text.count("- add: ") == 2
    assert parse_playbook(text) == {"add": "product"}
    # a header line is not a rule
    assert parse_playbook("# Playbook\n(empty)") == {}
    # and a check set is stable across calls, so the split is too
    assert check_tasks() == check_tasks()
