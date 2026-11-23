"""An unreadable run directory is reported, not crashed (#1236).

``status`` / ``show`` / ``diagnose`` / ``cancel`` catch ``RunStoreError``
only, and ``_read_json`` used to let ``json.load``'s ``JSONDecodeError``
escape; a ``status.json`` of the wrong shape (``[]``, a string) made
``RunStatus.from_dict`` raise ``TypeError`` / ``AttributeError``. Both
landed as a server traceback instead of ``{"error": …}``. The wrap lives
in ``runstore`` so every operator surface inherits the same sentence.
"""

from __future__ import annotations

import json
import os

import pytest

from agentdescent import runstore
from agentdescent.cli import main
from agentdescent.mcp import Tools


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)
    return str(tmp_path / "runs")


def _plant(tmp_path, store, *, status=None):
    dest = tmp_path / "artifact.md"
    rd = runstore.create({
        "kind": "text", "target": str(dest),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact", "agent": {"ref": "echo"}, "reflect": {"ref": "echo"},
    }, store=store)
    if status is not None:
        with open(rd.status_path, "w", encoding="utf-8") as fh:
            fh.write(status)
    return rd


def _mcp_error(tools, run_id, method):
    payload = getattr(tools, method)(run_id)
    assert isinstance(payload, dict), payload
    assert "error" in payload, payload
    return payload["error"]


def test_mcp_tools_name_a_status_that_is_not_json(tmp_path, store):
    rd = _plant(tmp_path, store, status="{not json")
    tools = Tools(store)
    prefix = f"cannot read run {rd.run_id!r}:"
    for method in ("status", "show", "diagnose", "cancel"):
        err = _mcp_error(tools, rd.run_id, method)
        assert err.startswith(prefix), (method, err)


def test_mcp_tools_name_a_status_of_the_wrong_shape(tmp_path, store):
    rd = _plant(tmp_path, store, status="[]")
    tools = Tools(store)
    prefix = f"cannot read run {rd.run_id!r}:"
    for method in ("status", "show"):
        err = _mcp_error(tools, rd.run_id, method)
        assert err.startswith(prefix), (method, err)


def test_cli_show_names_an_unreadable_status(tmp_path, store, capsys):
    rd = _plant(tmp_path, store, status="{not json")
    code = main(["--store", store, "show", rd.run_id, "--json"])
    assert code == 2
    doc = json.loads(capsys.readouterr().out)
    assert doc["ok"] is False
    assert doc["error"].startswith(f"cannot read run {rd.run_id!r}:")


def test_a_healthy_run_still_reads(tmp_path, store):
    rd = _plant(tmp_path, store)
    tools = Tools(store)
    st = tools.status(rd.run_id)
    assert st["run_id"] == rd.run_id
    assert st["state"] == "created"
    shown = tools.show(rd.run_id)
    assert shown["run_id"] == rd.run_id
    assert "error" not in shown or shown.get("state") == "created"


def test_a_missing_status_keeps_its_wording(tmp_path, store):
    rd = _plant(tmp_path, store)
    os.remove(rd.status_path)
    tools = Tools(store)
    expected = f"{rd.run_id}: no status.json; not a run directory"
    err = _mcp_error(tools, rd.run_id, "status")
    assert err == expected
    err = _mcp_error(tools, rd.run_id, "show")
    assert err == expected
