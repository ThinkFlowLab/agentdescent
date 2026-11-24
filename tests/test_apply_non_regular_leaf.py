"""A tree leaf that is not a regular file is refused, and reading one cannot block (#1225).

``#1223`` refused a leaf that is already a *directory* and ``#1231`` refuses the
two link shapes. The same class one object type over is a FIFO, a socket or a
device sitting where the artifact wants a file: ``_refuse_blocked_leaf`` tested
``os.path.isdir`` only, so ``show --diff`` and ``apply --dry-run`` advertised the
leaf as ``written``, the real ``apply`` died inside the ``shutil`` backup copy,
and ``apply --no-backup`` blocked forever in ``materialize``'s ``open(..., "w")``
*after* rewriting the leaves that sort before it -- a half-applied tree.

Two guards, one sentence on every surface. The write side is the funnel
(``_check_apply_paths`` -> ``_refuse_blocked_leaf``), which names the leaf before
anything is written or backed up. The read side is ``load_tree``, which refuses
a non-regular entry instead of blocking in ``open``: ``show --diff`` reads the
destination before the funnel runs, so the funnel alone would still hang there.

The rows that can block run out of process under a ``timeout 20`` ceiling, and
``rc == 124`` is the red: a regression must fail as a killed child inside the
test's own ceiling instead of hanging CI until the platform kills the job. The
failure message quotes the child's ``faulthandler`` dump, so it names the frame
that blocked rather than saying "still blocks".
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agentdescent import runstore
from agentdescent.cli import main
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical

#: This checkout, so the child imports the tree under test, not an install.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: The child's own ceiling. A blocked ``open`` never returns; the ceiling does.
CEILING = 20
#: When the child dumps its stack. Chosen so it fires inside the ceiling while
#: still leaving room for interpreter start plus imports (~1 s measured).
DUMP_AFTER = 12
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


def _tree_run(tmp_path, dest, state):
    store = str(tmp_path / "runs-tree")
    rd = runstore.create({
        "kind": "skill_library",
        "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "claude_code"},
        "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state=state, rendered=canonical(state), final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, str(rd.run_id)


def _show_plan(store, rid, capsys):
    code, out = _run_cli(
        ["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0, out.err or out.out
    return json.loads(out.out)["apply_plan"]


def _apply_error(argv, capsys):
    code, out = _run_cli(argv, capsys)
    assert code == 2, out.out or out.err
    doc = json.loads(out.out)
    assert doc["ok"] is False
    return doc["error"]


def _sentence(path, kind):
    """The refusal every surface must print for ``path`` of ``kind``."""
    return f"cannot write {path}: {str(path)!r} is {kind}"


def _fifo_dest(tmp_path):
    """A destination whose produced leaf is a FIFO, plus the run that writes it."""
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "SKILL.md").write_text("old\n", encoding="utf-8")
    leaf = dest / "references" / "rules.md"
    leaf.parent.mkdir()
    os.mkfifo(str(leaf))
    store, rid = _tree_run(
        tmp_path, dest, {"SKILL.md": "evolved\n", "references/rules.md": "new\n"})
    return dest, leaf, store, rid


def _backup_dirs(root):
    return sorted(
        os.path.join(dirpath, name)
        for dirpath, dirnames, _filenames in os.walk(str(root))
        for name in dirnames if name.startswith("bak-"))


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
            f"binary was available to report rc=124.\nchild stderr:\n{e.stderr[-1500:]}")


def _assert_returned(proc, what):
    """The child must return on its own: rc=124 is the ceiling firing, not a refusal."""
    if proc.returncode == 124:
        pytest.fail(
            f"{what} blocked: `timeout {CEILING}` killed the child (rc=124).\n"
            f"child stack:\n{proc.stderr[-1500:]}")
    if "Timeout (0:" in proc.stderr:
        pytest.fail(
            f"{what} reached the {DUMP_AFTER}s stack dump, so it nearly "
            f"blocked:\n{proc.stderr[-1500:]}")


# -- the write side: the funnel names the leaf before anything is written ------


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_leaf_is_named_by_the_dry_run(tmp_path, capsys):
    dest, leaf, store, rid = _fifo_dest(tmp_path)
    expected = _sentence(leaf, "a named pipe")
    assert _apply_error(
        ["--store", store, "apply", rid, "--dry-run", "--json"], capsys
    ) == expected
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old\n"
    assert stat.S_ISFIFO(os.lstat(str(leaf)).st_mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_leaf_is_named_by_the_real_apply(tmp_path, capsys):
    dest, leaf, store, rid = _fifo_dest(tmp_path)
    expected = _sentence(leaf, "a named pipe")
    assert _apply_error(
        ["--store", store, "apply", rid, "--json"], capsys) == expected
    # No half-applied tree: the leaf that sorts first was not written either,
    # the FIFO is intact, and no backup directory was taken.
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old\n"
    assert stat.S_ISFIFO(os.lstat(str(leaf)).st_mode)
    assert _backup_dirs(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_prune_refuses_to_delete_a_fifo_it_did_not_evolve(tmp_path):
    """``prune=True`` deletes extras, but not through a non-regular leaf (#1225).

    The funnel sees ``changed + deleted``, so the same refusal that stops a write
    to a FIFO keeps ``prune`` from clearing one. Base deleted it; the directory
    rule from ``#1223`` already refused a directory this way, and ``#1231``
    pinned the same shape for a stray symlink.
    """
    dest = tmp_path / "lib"
    dest.mkdir()
    (dest / "rules.md").write_text("x\n", encoding="utf-8")
    stray = dest / "stray"
    os.mkfifo(str(stray))
    state = {"rules.md": "x\n"}
    result = EvolutionResult(state=state, rendered=canonical(state),
                             final_reward=0.0, history=[], ledger_log=[])
    with pytest.raises(runstore.RunStoreError) as caught:
        result.write_to(str(dest), prune=True)
    assert str(caught.value) == _sentence(stray, "a named pipe")
    assert stat.S_ISFIFO(os.lstat(str(stray)).st_mode)


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_leaf_does_not_hang_apply_no_backup(tmp_path):
    """The row that used to hang: rc 2 and the sentence, inside the ceiling."""
    dest, leaf, store, rid = _fifo_dest(tmp_path)
    expected = _sentence(leaf, "a named pipe")
    proc = _run_capped(["--store", store, "apply", rid, "--no-backup", "--json"])
    _assert_returned(proc, "apply --no-backup")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False and doc["error"] == expected
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old\n"


# -- the read side: `show --diff` must return, and say the same sentence -------


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_leaf_is_named_by_show_diff(tmp_path):
    _dest, leaf, store, rid = _fifo_dest(tmp_path)
    expected = _sentence(leaf, "a named pipe")
    proc = _run_capped(["--store", store, "show", rid, "--diff", "--json"])
    _assert_returned(proc, "show --diff --json")
    assert proc.returncode == 0, proc.stderr
    plan = json.loads(proc.stdout)["apply_plan"]
    assert plan.get("error") == expected
    assert "written" not in plan


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_human_show_diff_is_named_and_does_not_block(tmp_path):
    _dest, leaf, store, rid = _fifo_dest(tmp_path)
    expected = _sentence(leaf, "a named pipe")
    proc = _run_capped(["--store", store, "show", rid, "--diff"])
    _assert_returned(proc, "show --diff")
    assert proc.returncode == 0, proc.stderr
    assert "apply would:" in proc.stdout
    assert expected in proc.stdout


# -- controls: the two neighbours this change must not disturb -----------------


def test_a_directory_leaf_keeps_its_wording(tmp_path, capsys):
    """``#1224``'s sentence stays byte-identical; compare by equality, not `in`."""
    dest = tmp_path / "lib"
    leaf = dest / "beta"
    leaf.mkdir(parents=True)
    store, rid = _tree_run(tmp_path, dest, {"beta": "evolved\n"})
    expected = f"cannot write {leaf}: {str(leaf)!r} is a directory, not a file"
    plan = _show_plan(store, rid, capsys)
    assert plan.get("error") == expected
    assert "written" not in plan
    assert _apply_error(
        ["--store", store, "apply", rid, "--dry-run", "--json"], capsys
    ) == expected
    assert _apply_error(
        ["--store", store, "apply", rid, "--json"], capsys) == expected
    assert leaf.is_dir()


def test_a_socket_leaf_is_refused(tmp_path, capsys):
    """The same rule one object over: a bound ``AF_UNIX`` socket at the leaf."""
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("no AF_UNIX sockets on this platform")
    # ``sun_path`` caps a bind at 108 bytes and ``tmp_path`` rides on TMPDIR, so
    # a long TMPDIR pushes ``tmp_path/lib/agent.sock`` over the cap before the
    # product is exercised (#1245). Move this one row under a short root when
    # the fixture's path is long; the socket still sits at ``lib/agent.sock``.
    relocated = len(str(tmp_path / "lib" / "agent.sock")) > 100
    if relocated and not os.path.isdir("/tmp"):
        pytest.skip("AF_UNIX leaf path exceeds sun_path and there is no short /tmp")
    root = Path(tempfile.mkdtemp(prefix="ad-sock-", dir="/tmp")) if relocated else tmp_path
    try:
        dest = root / "lib"
        dest.mkdir()
        leaf = dest / "agent.sock"
        with socket.socket(socket.AF_UNIX) as bound:
            bound.bind(str(leaf))
            store, rid = _tree_run(root, dest, {"agent.sock": "evolved\n"})
            expected = _sentence(leaf, "a socket")
            plan = _show_plan(store, rid, capsys)
            assert plan.get("error") == expected
            assert "written" not in plan
            assert _apply_error(
                ["--store", store, "apply", rid, "--dry-run", "--json"], capsys
            ) == expected
            assert _apply_error(
                ["--store", store, "apply", rid, "--json"], capsys) == expected
            assert stat.S_ISSOCK(os.lstat(str(leaf)).st_mode)
    finally:
        if relocated:
            shutil.rmtree(root, ignore_errors=True)
