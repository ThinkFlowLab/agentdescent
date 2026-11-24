"""Every workflow job declares a timeout, and the value is pinned here.

A job without ``timeout-minutes`` runs until GitHub's 360-minute default, so a
hung step -- the Pages deploy waiting on an environment, the publish jobs
waiting on an OIDC exchange -- holds a runner for six hours and shows up only
as a slow check.  A finite timeout turns that into a failed job in the hour it
happens.

The second test pins the integers: a bound is only useful if it sits above the
slowest *legitimate* run, so lowering one is a decision, not an edit nobody
notices.  ``tests.yml:test`` is 45 because the 3.9 leg measured 30m12s (run
45002962476) with two more at 29m54s -- a 30-minute bound would cancel a green
run, and the rule is bound >= ~1.4x the observed maximum.

The pin covers the whole repository, including jobs ``#1235`` does not touch.
That is deliberate (one table, one place to look), but it means the failure has
to explain itself: every assertion names the file, the job, the pinned value and
the value found, and it marks rows outside ``#1235``'s scope as pre-existing so
the next person editing a different job knows the table, not their change, is
what went red.

Offline: reads the workflow files in the checkout, no network, no fixtures.
"""

import yaml
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# workflow:job -> minutes, the whole repository. Raise a value only with the
# measurement that justifies it.
EXPECTED_TIMEOUTS = {
    "controller.yml:plan": 10,
    "controller.yml:apply": 10,
    "docs.yml:build": 15,
    "docs.yml:deploy": 15,
    "labels.yml:sync": 5,
    "publish-npm.yml:publish": 15,
    "publish.yml:build": 15,
    "publish.yml:publish": 15,
    "review-gate.yml:report": 5,
    "risk-tier.yml:report": 5,
    "tests.yml:otel-wire": 15,
    "tests.yml:test": 45,
}

# The seven rows #1235 sets; every other row already declared its timeout and is
# pinned as a side effect, which the failure message says out loud.
SET_BY_1235 = {
    "docs.yml:build",
    "docs.yml:deploy",
    "publish.yml:build",
    "publish.yml:publish",
    "publish-npm.yml:publish",
    "tests.yml:test",
    "tests.yml:otel-wire",
}


def _jobs(path):
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(config, dict), f"{path.name} is not a YAML mapping"
    return config.get("jobs") or {}


def _declared():
    """`workflow:job` -> declared value (None when the key is absent)."""
    return {
        f"{path.name}:{job}": (_jobs(path)[job] or {}).get("timeout-minutes")
        for path in WORKFLOWS
        for job in _jobs(path)
    }


def _scope(job):
    return "" if job in SET_BY_1235 else " (pre-existing value, not part of #1235's diff)"


def test_workflows_exist():
    assert WORKFLOWS, f"no workflow files found under {ROOT / '.github' / 'workflows'}"


def test_every_job_declares_a_timeout():
    declared = _declared()
    missing = [
        (
            f"  .github/workflows/{name.split(':')[0]} job `{name.split(':')[1]}`: "
            f"expected {EXPECTED_TIMEOUTS.get(name, 'an integer')} minutes, "
            f"found {declared[name]!r}{_scope(name)}"
        )
        for name in sorted(declared)
        if not isinstance(declared[name], int)
    ]
    assert not missing, (
        "every job must declare an integer `timeout-minutes`; without it GitHub "
        "kills the job at the 360-minute default, so a hung deploy or a stalled "
        "OIDC exchange holds a runner for hours:\n" + "\n".join(missing)
    )


@pytest.mark.parametrize(
    "workflow,job", sorted(tuple(name.split(":")) for name in EXPECTED_TIMEOUTS)
)
def test_timeout_value_is_pinned(workflow, job):
    name = f"{workflow}:{job}"
    declared = _declared()
    if name not in declared:
        pytest.fail(
            f".github/workflows/{workflow} has no job `{job}`; the pin table in "
            f"tests/test_workflow_job_timeouts.py expects {EXPECTED_TIMEOUTS[name]} "
            "minutes. Restore the job, or drop the row if it was renamed."
        )
    assert declared[name] == EXPECTED_TIMEOUTS[name], (
        f"workflow timeout drift: .github/workflows/{workflow} job `{job}` "
        f"declares {declared[name]!r} minutes, expected {EXPECTED_TIMEOUTS[name]} "
        f"minutes{_scope(name)}. A bound must stay above the slowest legitimate "
        "run; change the pin in this file only together with the measurement "
        "that justifies it."
    )


def test_no_unpinned_jobs():
    unpinned = sorted(set(_declared()) - set(EXPECTED_TIMEOUTS))
    assert not unpinned, (
        "a workflow job exists with no row in EXPECTED_TIMEOUTS, so nothing pins "
        "its timeout; add the job and its chosen value to "
        "tests/test_workflow_job_timeouts.py:\n  "
        + "\n  ".join(f".github/workflows/{n.split(':')[0]} job `{n.split(':')[1]}`" for n in unpinned)
    )
