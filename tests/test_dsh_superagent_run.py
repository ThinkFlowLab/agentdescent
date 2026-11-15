"""The long-run handoff (#964): the page's command, and the run outliving a turn.

Two checks, and neither needs a model:

* the documented command shape is real -- the wrapper exists and takes the
  flags the page passes it, and `agentdescent evolve` still answers `--detach`,
  which is the flag the page tells a worker to use;
* gated behind ``AGENTDESCENT_LONG_RUN_SMOKE=1``, a fake run longer than the
  caller's own limit survives the caller's turn: the wrapper returns while the
  run is still going, the report names the run id and round, and no tmux
  session (hence no orphan) is left once it finishes.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WRAPPER = REPO / "scripts" / "dsh-superagent-run.sh"
PAGE = REPO / "docs" / "dsh-super-agent.md"

FAKE = '''
import json, os, sys, time
store = sys.argv[1]
run_dir = os.path.join(store, "fake-run-1")
os.makedirs(run_dir, exist_ok=True)
path = os.path.join(run_dir, "status.json")

def write(**kw):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(kw, fh)

write(run_id="fake-run-1", round=2, state="running", pid=os.getpid())
time.sleep(3)
write(run_id="fake-run-1", round=3, state="finished", pid=os.getpid())
'''


def _page_handoff_example() -> str:
    """The page's fenced example that starts a run through the wrapper."""
    page = PAGE.read_text(encoding="utf-8")
    for block in page.split("```"):
        if "scripts/dsh-superagent-run.sh" in block:
            return block
    raise AssertionError("the page has no example that starts the wrapper")


def test_the_page_hands_the_run_the_store_the_wrapper_reports_into():
    # Two stores, one variable. The wrapper's `--store` is where the report
    # goes; the run's store is the CLI's own global flag. Naming only the
    # wrapper's store made `evolve` write to the default store, so the wrapper
    # waited out its deadline and reported found: false, and the page's
    # read-back could not find the run (#1084 review).
    example = " ".join(_page_handoff_example().split())
    assert 'dsh-superagent-run.sh --store "$RUN_STORE" --' in example, example
    assert 'agentdescent --store "$RUN_STORE" evolve' in example, example


def test_the_page_documents_a_wrapper_that_exists_and_takes_its_flags():
    assert WRAPPER.is_file(), f"no {WRAPPER}"
    # Invoked as `bash scripts/dsh-superagent-run.sh`, the way the page and
    # `scripts/verify-dsh-superagent.sh` (committed 644) are, so the mode is not
    # part of the contract; the command shape below is.
    page = PAGE.read_text(encoding="utf-8")
    assert "scripts/dsh-superagent-run.sh" in page, "the page does not name the wrapper"
    assert "--store" in page and "--detach" in page
    helped = subprocess.run(["bash", str(WRAPPER), "--help"], cwd=REPO,
                            capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0, helped.stderr
    assert "--store" in helped.stdout, "the wrapper's usage omits --store"
    evolve = subprocess.run(
        [sys.executable, "-m", "agentdescent.cli", "evolve", "--help"],
        cwd=REPO, capture_output=True, text=True, timeout=120)
    assert evolve.returncode == 0, evolve.stderr
    assert "--detach" in evolve.stdout, "the page tells a worker to pass a flag the CLI dropped"


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_a_run_outlives_the_turn_that_started_it_and_leaves_no_orphan(tmp_path):
    store = tmp_path / "runs"
    fake = tmp_path / "fake_run.py"
    fake.write_text(FAKE, encoding="utf-8")

    started = time.monotonic()
    handed = subprocess.run(
        ["bash", str(WRAPPER), "--store", str(store), "--",
         sys.executable, str(fake), str(store)],
        cwd=REPO, capture_output=True, text=True, timeout=60)
    elapsed = time.monotonic() - started

    assert handed.returncode == 0, handed.stderr
    assert elapsed < 2.0, f"the handoff blocked for {elapsed:.1f}s, so it held the slot"
    report = json.loads((store / "waiting.json").read_text(encoding="utf-8"))
    assert report["status"] == "waiting"
    assert report["found"] is True
    assert report["run_id"] == "fake-run-1"
    assert report["round"] == 2
    assert Path(report["run_dir"]).name == "fake-run-1"

    # The caller's turn is over and the run is still going: that is the handoff.
    pid = json.loads((Path(report["run_dir"]) / "status.json")
                     .read_text(encoding="utf-8"))["pid"]
    os.kill(pid, 0)

    deadline = time.monotonic() + 30
    status = {}
    while time.monotonic() < deadline:
        status = json.loads((Path(report["run_dir"]) / "status.json")
                            .read_text(encoding="utf-8"))
        if status["state"] == "finished":
            break
        time.sleep(0.2)
    assert status["state"] == "finished", status
    assert status["round"] == 3

    if report["driver"] == "tmux" and shutil.which("tmux"):
        # The run writes `finished` before its own process exits, and tmux
        # destroys the session after the pane's command ends, so the session is
        # still listed for a moment -- measured ~1.7s on a loaded host. Poll for
        # it to go; only a session that stays is an orphan. `=` asks for that
        # exact name: a bare target also prefix-matches a longer one, so
        # `-t ad-runs` can answer about an unrelated ad-runs-2.
        poll_started = time.monotonic()
        deadline = poll_started + 15
        left = 0
        while time.monotonic() < deadline:
            left = subprocess.run(
                ["tmux", "has-session", "-t", "=" + report["session"]],
                capture_output=True, text=True).returncode
            if left != 0:
                break
            time.sleep(0.1)
        waited = time.monotonic() - poll_started
        assert left != 0, (
            f"orphan tmux session {report['session']!r} still listed after "
            f"{waited:.1f}s (last `tmux has-session` rc={left})")


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_a_reused_store_does_not_report_an_earlier_run(tmp_path):
    # A store is reused for every Ticket, so it always holds earlier runs. The
    # first poll used to take the newest `*/status.json` it could see and report
    # that run -- a finished one -- as the handoff (#1084 review). Nothing here
    # writes a status.json, so the report must say it found nothing.
    store = tmp_path / "runs"
    old = store / "old-run"
    old.mkdir(parents=True)
    (old / "status.json").write_text(
        json.dumps({"run_id": "old-run", "round": 7, "state": "finished"}),
        encoding="utf-8")
    handed = subprocess.run(
        ["bash", str(WRAPPER), "--store", str(store), "--", "sleep", "1"],
        cwd=REPO, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, DSH_RUN_HANDOFF_WAIT="1"))
    assert handed.returncode == 0, handed.stderr
    report = json.loads((store / "waiting.json").read_text(encoding="utf-8"))
    assert report["found"] is False, report
    assert report["run_id"] == "", report
    assert report["round"] == 0, report
    assert os.path.realpath(report["run_dir"]) == os.path.realpath(str(store)), report


@pytest.mark.skipif(os.environ.get("AGENTDESCENT_LONG_RUN_SMOKE") != "1",
                    reason="set AGENTDESCENT_LONG_RUN_SMOKE=1 to run the detached smoke")
def test_two_handoffs_into_stores_called_runs_do_not_take_one_session(tmp_path):
    # The session name came from the store's basename, so two handoffs into
    # stores both called `runs` asked tmux for the same session and the second
    # died with "tmux refused the session" (#1084 review).
    if not shutil.which("tmux"):
        pytest.skip("no tmux on this host: the setsid fallback has no session name")
    fake = tmp_path / "fake_run.py"
    fake.write_text(FAKE, encoding="utf-8")
    reports = []
    for name in ("a", "b"):
        store = tmp_path / name / "runs"
        handed = subprocess.run(
            ["bash", str(WRAPPER), "--store", str(store), "--",
             sys.executable, str(fake), str(store)],
            cwd=REPO, capture_output=True, text=True, timeout=60)
        assert handed.returncode == 0, handed.stderr
        reports.append(json.loads((store / "waiting.json").read_text(encoding="utf-8")))
    assert reports[0]["driver"] == "tmux", reports
    assert reports[0]["session"] and reports[1]["session"], reports
    assert reports[0]["session"] != reports[1]["session"], reports

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and any(
            subprocess.run(["tmux", "has-session", "-t", "=" + report["session"]],
                           capture_output=True, text=True).returncode == 0
            for report in reports):
        time.sleep(0.1)
