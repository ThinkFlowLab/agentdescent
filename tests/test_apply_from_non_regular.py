"""`apply --from` refuses a non-regular entry in the source tree (#1246).

``_files`` classified the source tree with ``os.path.islink`` and nothing else,
so a FIFO sitting where the artifact expects a file was returned as a *planned*
file and the comparison opened it: ``_same`` does ``open(a_path, "rb")`` on the
source path, which blocks until a peer appears -- forever, when none does. The
funnel that names a blocked leaf (``_check_apply_paths``) runs later and on the
``--to`` side, so it cannot catch this one.

Measured on ``main`` at ``22ea7528``: a FIFO at
``src/references/rules.md`` with a regular file at the same rel in ``--to``
under a 60 s ceiling gives rc=124, and the stack ends in ``_same``.

The rows that can block run out of process under a ``timeout 60`` ceiling, and
rc 124 is the red: a regression fails as a killed child inside the test's own
ceiling instead of hanging CI until the platform kills the job.

The control at the bottom is the other half of the contract: two regular trees
must plan and apply exactly as before.
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

#: This checkout, so the child imports the tree under test, not an install.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: The child's own ceiling: a cold start plus fixture build can cross 20 s on a
#: loaded box, so a refusal row would die as a false ``rc=124``. A blocked
#: ``open`` still never returns; the ceiling does.
CEILING = 60
#: When the child dumps its stack. It fires inside the ceiling so a real hang
#: yields a stack before the kill, while a cold start plus fixture build stays
#: far below it; 45 s leaves 15 s before the 60 s ceiling.
DUMP_AFTER = 45
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
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(tmp_path))


def _run_capped(argv):
    """Run the CLI in a child under the ceiling; never inherit the ceiling's absence."""
    if TIMEOUT is None:                     # pragma: no cover - POSIX CI has it
        pytest.skip("`timeout` is not on PATH")
    return subprocess.run(
        [TIMEOUT, str(CEILING), sys.executable, "-c", CHILD, *argv],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )


def _assert_returned(proc, what):
    if proc.returncode == 124:
        pytest.fail(
            f"{what} blocked: `timeout {CEILING}` killed the child (rc=124).\n"
            f"child stack:\n{proc.stderr[-1500:]}")
    if "Timeout (0:" in proc.stderr:
        pytest.fail(
            f"{what} reached the {DUMP_AFTER}s stack dump, so it nearly "
            f"blocked:\n{proc.stderr[-1500:]}")


def _two_trees(tmp_path):
    """``src`` with a regular file, ``--to`` at the same rel, and a change."""
    src = tmp_path / "src"
    dest = tmp_path / "lib"
    (src / "references").mkdir(parents=True)
    (src / "SKILL.md").write_text("new\n", encoding="utf-8")
    (src / "references" / "rules.md").write_text("rules new\n", encoding="utf-8")
    (dest / "references").mkdir(parents=True)
    (dest / "SKILL.md").write_text("old\n", encoding="utf-8")
    (dest / "references" / "rules.md").write_text("rules old\n", encoding="utf-8")
    return src, dest


def _backup_dirs(root):
    return sorted(
        os.path.join(dirpath, name)
        for dirpath, _dirnames, _filenames in os.walk(str(root))
        for name in _dirnames if name.startswith("bak-"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_in_the_source_is_named_by_the_dry_run(tmp_path):
    src, dest = _two_trees(tmp_path)
    os.unlink(str(src / "references" / "rules.md"))
    os.mkfifo(str(src / "references" / "rules.md"))
    proc = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest),
                        "--dry-run"])
    _assert_returned(proc, "apply --from --dry-run with a FIFO source")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "'references/rules.md' is a named pipe" in doc["error"], doc["error"]
    # Nothing was read, written, or backed up.
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old\n"
    assert (dest / "references" / "rules.md").read_text(encoding="utf-8") == "rules old\n"
    assert stat.S_ISFIFO(os.lstat(str(src / "references" / "rules.md")).st_mode)
    assert _backup_dirs(dest) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO")
def test_a_fifo_in_the_source_is_named_by_the_real_run(tmp_path):
    src, dest = _two_trees(tmp_path)
    os.unlink(str(src / "references" / "rules.md"))
    os.mkfifo(str(src / "references" / "rules.md"))
    proc = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest)])
    _assert_returned(proc, "apply --from with a FIFO source")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "'references/rules.md' is a named pipe" in doc["error"], doc["error"]
    # Refused before the funnel: no leaf was written and no backup slot was taken.
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "old\n"
    assert _backup_dirs(dest) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX socket")
def test_a_socket_in_the_source_is_named(tmp_path, monkeypatch):
    # ``sun_path`` caps a bind at 108 bytes and ``tmp_path`` rides on TMPDIR, so
    # a long TMPDIR pushes ``src/references/rules.md`` over the cap before the
    # product is exercised (#1245). Build this row under a short root when the
    # fixture's path is long; the refusal under test is unchanged.
    relocated = len(str(tmp_path / "src" / "references" / "rules.md")) > 100
    if relocated and not os.path.isdir("/tmp"):
        pytest.skip("AF_UNIX leaf path exceeds sun_path and there is no short /tmp")
    root = Path(tempfile.mkdtemp(prefix="ad-sock-", dir="/tmp")) if relocated else tmp_path
    if relocated:
        monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS",
                           ",".join((str(tmp_path), str(root))))
    try:
        src, dest = _two_trees(root)
        sock_path = str(src / "references" / "rules.md")
        os.unlink(sock_path)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.bind(sock_path)
            try:
                proc = _run_capped(["--json", "apply", "--from", str(src),
                                    "--to", str(dest), "--dry-run"])
                _assert_returned(proc, "apply --from with a socket source")
            finally:
                s.close()
        assert proc.returncode == 2, proc.stdout + proc.stderr
        doc = json.loads(proc.stdout)
        assert doc["ok"] is False
        assert "'references/rules.md' is a socket" in doc["error"], doc["error"]
    finally:
        if relocated:
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX character device")
@pytest.mark.skipif(not os.path.exists("/dev/null"), reason="no /dev/null")
def test_a_character_device_in_the_source_is_named(tmp_path):
    """Where the platform lets a device be placed in an ordinary directory."""
    src, dest = _two_trees(tmp_path)
    probe = tmp_path / "probe-dev"
    try:
        os.mknod(str(probe), stat.S_IFCHR | 0o600, os.makedev(1, 3))
        os.unlink(str(probe))
    except (OSError, AttributeError):
        pytest.skip("this platform/user cannot create a device node")
    os.mknod(str(src / "references" / "rules.md"), stat.S_IFCHR | 0o600,
             os.makedev(1, 3))
    proc = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest),
                        "--dry-run"])
    _assert_returned(proc, "apply --from with a device source")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    doc = json.loads(proc.stdout)
    assert doc["ok"] is False
    assert "'references/rules.md' is a character device" in doc["error"], doc["error"]


def test_two_regular_trees_still_apply(tmp_path):
    """The control: nothing about a regular source tree changed."""
    src, dest = _two_trees(tmp_path)
    dry = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest),
                       "--dry-run"])
    assert dry.returncode == 0, dry.stdout + dry.stderr
    plan = json.loads(dry.stdout)
    assert plan["written"] == ["references/rules.md", "SKILL.md"] or \
        plan["written"] == ["SKILL.md", "references/rules.md"], plan["written"]
    real = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest)])
    assert real.returncode == 0, real.stdout + real.stderr
    assert (dest / "SKILL.md").read_text(encoding="utf-8") == "new\n"
    assert (dest / "references" / "rules.md").read_text(encoding="utf-8") == "rules new\n"
    again = _run_capped(["--json", "apply", "--from", str(src), "--to", str(dest)])
    assert again.returncode == 0, again.stdout + again.stderr
    assert json.loads(again.stdout)["noop"] is True
