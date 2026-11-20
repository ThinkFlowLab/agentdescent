"""A parked draft is not in the review queue (issue #1192).

The controller runs on a cron and labels every open pull request, so a draft
that nobody asked to review yet used to get ``agent-pr`` and ``risk:T*`` and
appear in the queue. ``read_prs`` already fetches the pull list, which carries
``draft``; the plan skips such a PR with the ``skipped`` reason ``draft`` —
no add and no remove, so the labels it already has stay. ``hold`` still wins.
"""

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
CONFIG = json.loads((ROOT / ".github" / "agent" / "controller.json").read_text())


def _mod():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("controller", SCRIPTS / "controller.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(SCRIPTS))


c = _mod()
REPO = "ThinkFlowLab/agentdescent"
ALL = ["agent-ready", "agent-working", "agent-pr", "hold", "risk:T0", "risk:T1", "risk:T2", "risk:T3"]
NOW = c.parse_time("2026-10-19T12:00:00Z")


def pr(number, labels=(), tier="T1", author="HugoXK", head="feat/x", same=True, body="",
       push="2026-10-19T11:00:00Z", draft=False):
    return {"number": number, "labels": list(labels), "tier": tier, "author": author, "headRef": head,
            "sameRepo": same, "body": body, "lastPushAt": push, "draft": draft}


def run(prs=(), labels=ALL):
    prs = list(prs)
    return c.plan({"repo": REPO, "config": CONFIG, "now": NOW, "repoLabels": list(labels),
                   "issues": [], "prs": prs, "linked": c.linked_prs(prs, REPO)})


class PullApi:
    """The two GETs ``read_prs`` makes per PR, and nothing else."""

    def __init__(self, pulls):
        self.pulls, self.calls = pulls, []

    def get(self, path):
        self.calls.append(("GET", path))
        if path.startswith(f"repos/{REPO}/pulls?"):
            return self.pulls
        if "/commits/" in path:
            return {"commit": {"committer": {"date": "2026-10-19T11:00:00Z"}}}
        raise AssertionError(path)

    def list(self, path):
        self.calls.append(("LIST", path))
        return [{"filename": "docs/x.md", "status": "modified", "additions": 1, "deletions": 0}]


class StubGate:
    def judge(self, files):
        return {"tier": "T1"}


def pull(number, draft):
    return {"number": number, "draft": draft, "labels": [], "user": {"login": "HugoXK"},
            "head": {"ref": f"feat/{number}", "sha": f"{number:040x}", "repo": {"full_name": REPO}},
            "body": "", "created_at": "2026-10-19T11:00:00Z"}


def test_read_prs_records_the_draft_flag_it_already_fetches():
    api = PullApi([pull(41, True), pull(42, False)])
    prs = c.read_prs(api, REPO, CONFIG, StubGate())
    assert [(p["number"], p["draft"]) for p in prs] == [(41, True), (42, False)]
    # The pull list already carries the field: a draft costs no extra request.
    draft_calls = [x for x in api.calls if x[0] == "GET" and "/pulls/" in x[1] and "draft" in x[1]]
    assert draft_calls == []
    assert len([x for x in api.calls if "/pulls/41" in x[1]]) == len([x for x in api.calls if "/pulls/42" in x[1]])


def test_a_draft_pr_is_skipped_and_keeps_the_labels_it_has():
    parked = pr(20, ["agent-pr", "risk:T2"], tier="T3", head="agent/x", draft=True)
    out = run(prs=[parked])
    assert out["ops"] == [], "a draft must not be labelled, and must not lose a label either"
    assert {"number": 20, "label": "*", "reason": "draft"} in out["skipped"]


def test_a_ready_pr_next_to_it_is_labelled_normally():
    parked = pr(20, ["agent-pr", "risk:T2"], tier="T3", head="agent/x", draft=True)
    ready = pr(21, tier="T1", head="agent/x", draft=False)
    out = run(prs=[parked, ready])
    assert {(o["number"], o["op"], o["label"]) for o in out["ops"]} == {
        (21, "add", "risk:T1"), (21, "add", "agent-pr")}
    assert not any(s["number"] == 21 for s in out["skipped"]), "the control row stays untouched"


def test_hold_is_still_reported_first_on_a_draft():
    out = run(prs=[pr(22, ["hold"], tier="T2", draft=True)])
    assert out["ops"] == []
    assert out["skipped"] == [{"number": 22, "label": "*", "reason": "hold"}]


def test_the_draft_reason_needs_no_new_plan_key_and_renders():
    out = run(prs=[pr(30, draft=True, tier="T2")])
    assert set(out) == {"ops", "skipped", "notes"}, "apply/validate_plan see the same plan shape"
    assert "draft" not in c.REASONS, "a skipped PR never becomes an operation"
    text = c.render(dict(out, version=1), "dry-run")
    assert "- #30 `?`: draft" in text
