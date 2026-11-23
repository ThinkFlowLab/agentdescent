"""Every workflow job bounds its own run time.

A job without ``timeout-minutes`` inherits GitHub's 360-minute default, so a
stalled step -- a Pages deploy waiting on its OIDC exchange, a publish job
holding ``id-token: write``, a test runner blocked on a hung fixture -- reads as
a slow check for six hours instead of a stuck one.

The bounds are calibrated from this repository's own run history (Actions API,
read 2026-11-23), not from round numbers:

====================  =================  =====
job                   observed minutes   bound
====================  =================  =====
docs build            1.3 - 2.8          10
docs deploy           0.0 - 0.1           5
publish build         0.6 - 0.9          10
publish publish       0.3 - 0.4           5
publish-npm publish   0.2 - 0.3           5
tests test (per Py)   15.7 - 29.9        60
tests otel-wire       1.2 - 1.4          10
====================  =================  =====

``tests`` keeps the largest bound on purpose: a 5- or 10-minute cap on a matrix
job that takes twenty would turn green PRs red, and these caps exist to catch a
hang, not to race a healthy run.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
MAXIMUM = 60


def _jobs():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, job in (wf.get("jobs") or {}).items():
            yield path.name, name, job


def test_every_job_declares_timeout_minutes():
    missing = [
        f"{wf}:{job}"
        for wf, job, spec in _jobs()
        if spec.get("timeout-minutes") is None
    ]
    assert not missing, (
        "a job without `timeout-minutes` inherits GitHub's 360-minute default, "
        f"so one stalled step holds the runner for six hours: {missing}"
    )


def test_no_job_is_bound_above_the_slowest_observed_suite():
    too_long = [
        (wf, job, spec.get("timeout-minutes"))
        for wf, job, spec in _jobs()
        if not 1 <= spec.get("timeout-minutes", 0) <= MAXIMUM
    ]
    assert not too_long, (
        f"keep every job bound at or below {MAXIMUM} minutes, or a hang still "
        f"reads as a slow check: {too_long}"
    )


def test_the_test_matrix_keeps_headroom_above_its_measured_runtime():
    wf = yaml.safe_load((WORKFLOWS / "tests.yml").read_text(encoding="utf-8"))
    limit = wf["jobs"]["test"].get("timeout-minutes")
    assert limit is not None and limit >= 45, (
        "the test job runs the whole offline suite across five Pythons and "
        "measured 15.7-29.9 minutes per version on 2026-11-23, so a bound "
        "under 45 would cut a healthy run instead of catching a hung one"
    )
