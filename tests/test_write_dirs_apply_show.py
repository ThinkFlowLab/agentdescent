"""``show --diff`` must not advertise the write ``apply`` refuses (#1188).

``apply`` checks the destination, every written leaf and the backup slot before
anything touches disk. A directory artifact backs up under
``$AGENTDESCENT_HOME/backups/...`` -- not beside the target -- so a destination
inside ``AGENTDESCENT_SURFACE_WRITE_DIRS`` whose home is outside it is a write
``apply`` refuses. ``show`` used to check only the destination and report that
same plan as ``written``: a preview for a call that exits 2.
"""

import json

import pytest

from agentdescent import runstore
from agentdescent.cli import NESTED_ENV, main
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical
from tests.test_skill_library_apply_install import _make_library_run


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    # Directory backups land here; each test decides whether that is inside or
    # outside the allowlist it sets.
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "ad-home"))


def _run_cli(argv, capsys):
    code = main(argv)
    return code, capsys.readouterr()


def test_show_refuses_a_plan_whose_directory_backup_is_outside_the_allowlist(
        tmp_path, capsys, monkeypatch):
    store, rid = _make_library_run(tmp_path)
    dest = tmp_path / "seed-lib"       # the run's target: inside the allowlist
    home = tmp_path / "ad-home"        # ... but its directory backup is not
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(dest))
    before = (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8")

    code, out = _run_cli(["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0
    plan = json.loads(out.out)["apply_plan"]
    assert "write allowlist" in plan.get("error", ""), (
        "show advertised a write it cannot apply: " + json.dumps(plan))
    assert str(home) in plan["error"]   # the refused backup path is named ...
    assert str(dest) in plan["error"]   # ... beside the allowed root

    code, out = _run_cli(["--store", store, "apply", rid, "--to", str(dest)], capsys)
    assert code == 2
    assert "write allowlist" in out.err
    assert (dest / "alpha" / "SKILL.md").read_text(encoding="utf-8") == before
    assert not home.exists()


def test_show_still_reports_a_text_plan_inside_the_allowlist(
        tmp_path, capsys, monkeypatch):
    # A text artifact backs up to a sibling `.bak-N`, inside the allowlist when
    # the destination is: that plan stays green, unchanged.
    store = str(tmp_path / "runs")
    target = tmp_path / "allowed" / "prompt.txt"
    target.parent.mkdir()
    target.write_text("edited since the run\n", encoding="utf-8")
    rd = runstore.create({
        "kind": "text", "target": str(target),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact", "agent": {"ref": "echo"}, "reflect": {"ref": "echo"},
    }, store=store)
    EvolutionResult(state={}, rendered="new text\n", final_reward=1.0,
                    history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(target.parent))

    code, out = _run_cli(["--store", store, "show", str(rd.run_id), "--diff",
                          "--json"], capsys)
    assert code == 0
    plan = json.loads(out.out)["apply_plan"]
    assert plan.get("error") is None
    assert plan["written"] == [str(target)]

    code, out = _run_cli(["--store", store, "apply", str(rd.run_id),
                          "--to", str(target)], capsys)
    assert code == 0
    assert target.read_text(encoding="utf-8") == "new text\n"
    assert (target.parent / "prompt.txt.bak-0").read_text(
        encoding="utf-8") == "edited since the run\n"


def test_show_keeps_allow_anywhere_when_the_allowlist_is_unset(
        tmp_path, capsys, monkeypatch):
    # Unset outside a worker is not "refuse everything": the plan is still shown.
    store, rid = _make_library_run(tmp_path)
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)
    monkeypatch.delenv(NESTED_ENV, raising=False)

    code, out = _run_cli(["--store", store, "show", rid, "--diff", "--json"], capsys)
    assert code == 0
    plan = json.loads(out.out)["apply_plan"]
    assert plan.get("error") is None
    assert plan["written"]
