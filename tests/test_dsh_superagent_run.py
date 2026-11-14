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
        left = subprocess.run(["tmux", "has-session", "-t", report["session"]],
                              capture_output=True, text=True)
        assert left.returncode != 0, f"orphan tmux session {report['session']}"
