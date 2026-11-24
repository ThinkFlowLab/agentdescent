"""A text destination that is not a regular file is refused, not opened (#1248).

``show``, ``show --diff``, ``apply --dry-run`` and ``apply`` all decide
``unchanged`` by opening the destination first (``_text_plan``), and the only
destination refusal on that path (``_refuse_text_dest``) tested a directory and a
link. A named pipe at ``target`` therefore blocked forever in ``open`` -- no
writer is ever coming -- on all four surfaces, and ``apply --from <file> --to
<fifo>`` blocked the same way because ``apply_from_payload`` calls
``_text_plan`` with no text-destination refusal at all.

The tree kind already refuses this class before its read (:func:`filetree.
load_tree`) and before its write (``_refuse_blocked_leaf``); a text artifact has
no ``load_tree``, so its own refusal has to come first.

Every row that can block runs out of process under a ``timeout`` ceiling, and
``rc == 124`` is the red: a regression must die as a killed child inside this
test's own ceiling instead of hanging CI until the platform kills the job. The
child dumps its stack before the ceiling fires, so a failing row names the frame
that blocked instead of saying "still blocks".
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

from agentdescent import runstore
from agentdescent.cli import main
from agentdescent.evolution import EvolutionResult

#: This checkout, so the child imports the tree under test, not an install.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: The child's own ceiling. A blocked ``open`` never returns; the ceiling does.
CEILING = 10
#: When the child dumps its stack. Inside the ceiling, after imports are done.
DUMP_AFTER = 6
TIMEOUT = shutil.which("timeout")
CHILD = (
    "import faulthandler, sys; "
    f"faulthandler.dump_traceback_later({DUMP_AFTER}); "
    "from agentdescent.cli import main; "
    "sys.exit(main(sys.argv[1:]))"
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "ad-home"))
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)


def _run_cli(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr()


def _text_run(tmp_path, dest, rendered="hello\n"):
    store = str(tmp_path / "runs")
    rd = runstore.create({
        "kind": "text", "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact", "agent": {"ref": "echo"}, "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state={}, rendered=rendered, final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, str(rd.run_id)


def _child_env():
    env = dict(os.environ)
    env["PYTHONPATH"] = REPO_ROOT + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _run_capped(args):
    """Run the CLI in a child under ``timeout CEILING``; never outlive the test."""
    argv = [sys.executable, "-c", CHILD, *args]
    if TIMEOUT:
        argv = [TIMEOUT, str(CEILING), *argv]
    try:
        return subprocess.run(
            argv, cwd=REPO_ROOT, env=_child_env(), capture_output=True,
            text=True, timeout=CEILING + 15)
    except subprocess.TimeoutExpired as e:  # no coreutils `timeout` on this host
        assert False, (
            f"{' '.join(args)} did not return within {CEILING}s and no `timeout` "
            f"binary was available to report rc=124.\nchild stderr:\n"
            f"{(e.stderr or '')[-1500:]}")


def _assert_returned(proc, what):
    """The child must return on its own: rc=124 is the ceiling firing."""
    if proc.returncode == 124:
        pytest.fail(
            f"{what} blocked: `timeout {CEILING}` killed the child (rc=124).\n"
            f"child stack:\n{proc.stderr[-1500:]}")
    if "Timeout (0:" in proc.stderr:
        pytest.fail(
            f"{what} reached the {DUMP_AFTER}s stack dump, so it nearly "
            f"blocked:\n{proc.stderr[-1500:]}")


def _fifo_dest(tmp_path):
    """A text artifact whose ``target`` is a named pipe."""
    dest = tmp_path / "prompt.txt"
    os.mkfifo(str(dest))
    store, rid = _text_run(tmp_path, dest)
    return dest, store, rid


def _backup_slots(root):
    """Sibling ``.bak-N`` files a text apply would have taken."""
    return sorted(
        os.path.join(dirpath, name)
        for dirpath, _dirnames, filenames in os.walk(str(root))
        for name in filenames if ".bak-" in name)


def _assert_fifo_intact(dest):
    assert stat.S_ISFIFO(os.lstat(str(dest)).st_mode), "the FIFO was replaced"


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_show_diff_names_a_fifo_target_instead_of_blocking(tmp_path):
    dest, store, rid = _fifo_dest(tmp_path)
    proc = _run_capped(["--store", store, "show", rid, "--diff", "--json"])
    _assert_returned(proc, "show --diff --json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    plan = json.loads(proc.stdout)["apply_plan"]
    assert plan.get("error"), "show advertised a write into a FIFO: " + json.dumps(plan)
    assert "is a named pipe" in plan["error"]
    _assert_fifo_intact(dest)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_show_names_a_fifo_target_instead_of_blocking(tmp_path):
    dest, store, rid = _fifo_dest(tmp_path)
    proc = _run_capped(["--store", store, "show", rid, "--json"])
    _assert_returned(proc, "show --json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    plan = json.loads(proc.stdout)["apply_plan"]
    assert plan.get("error"), "show advertised a write into a FIFO: " + json.dumps(plan)
    assert "is a named pipe" in plan["error"]
    _assert_fifo_intact(dest)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_apply_dry_run_refuses_a_fifo_target(tmp_path):
    dest, store, rid = _fifo_dest(tmp_path)
    proc = _run_capped(["--store", store, "apply", rid, "--dry-run", "--json"])
    _assert_returned(proc, "apply --dry-run --json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "is a named pipe" in doc["error"]
    _assert_fifo_intact(dest)
    assert _backup_slots(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_apply_refuses_a_fifo_target(tmp_path):
    dest, store, rid = _fifo_dest(tmp_path)
    proc = _run_capped(["--store", store, "apply", rid, "--json"])
    _assert_returned(proc, "apply --json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "is a named pipe" in doc["error"]
    _assert_fifo_intact(dest)
    assert _backup_slots(tmp_path) == [], "a refused apply took a backup slot"


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_show_and_apply_print_the_same_sentence_for_a_fifo_target(tmp_path):
    """#1204: the preview carries ``apply``'s own bytes, and exits 0."""
    dest, store, rid = _fifo_dest(tmp_path)
    show = _run_capped(["--store", store, "show", rid, "--diff", "--json"])
    _assert_returned(show, "show --diff --json")
    assert show.returncode == 0, show.stdout + show.stderr
    show_error = json.loads(show.stdout)["apply_plan"].get("error")
    assert show_error and "is a named pipe" in show_error

    applied = _run_capped(["--store", store, "apply", rid, "--json"])
    _assert_returned(applied, "apply --json")
    assert applied.returncode == 2, applied.stdout + applied.stderr
    assert json.loads(applied.stdout)["error"] == show_error
    _assert_fifo_intact(dest)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_from_file_to_a_fifo_dest_is_refused_by_the_dry_run(tmp_path):
    source = tmp_path / "SKILL.md"
    source.write_text("hello\n", encoding="utf-8")
    dest = tmp_path / "prompt.txt"
    os.mkfifo(str(dest))
    proc = _run_capped(
        ["apply", "--from", str(source), "--to", str(dest), "--dry-run", "--json"])
    _assert_returned(proc, "apply --from <file> --to <fifo> --dry-run --json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "is a named pipe" in doc["error"]
    _assert_fifo_intact(dest)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_from_file_to_a_fifo_dest_is_refused_by_the_real_apply(tmp_path):
    source = tmp_path / "SKILL.md"
    source.write_text("hello\n", encoding="utf-8")
    dest = tmp_path / "prompt.txt"
    os.mkfifo(str(dest))
    proc = _run_capped(
        ["apply", "--from", str(source), "--to", str(dest), "--json"])
    _assert_returned(proc, "apply --from <file> --to <fifo> --json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "is a named pipe" in doc["error"]
    _assert_fifo_intact(dest)
    assert _backup_slots(tmp_path) == []


def test_a_regular_target_still_plans_and_writes(tmp_path, capsys):
    """The control: nothing about a regular destination changes."""
    dest = tmp_path / "prompt.txt"
    dest.write_text("old\n", encoding="utf-8")
    store, rid = _text_run(tmp_path, dest, rendered="new text\n")

    code, out = _run_cli(["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    plan = json.loads(out.out)["apply_plan"]
    assert plan.get("error") is None
    assert plan["written"] == [str(dest)]
    assert plan["noop"] is False
    assert dest.read_text(encoding="utf-8") == "old\n"

    code, out = _run_cli(["--store", store, "apply", rid, "--json"], capsys)
    assert code == 0, out.err or out.out
    assert dest.read_text(encoding="utf-8") == "new text\n"
