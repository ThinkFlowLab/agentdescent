"""The demo footer must name the limit that stopped the run, not blame the demo.

`AGENTDESCENT_MAX_CALLS=1 agentdescent demo` exits 1 at `round 0/4` with reward
`0.000`, and the fixed sentence it prints says the result is "lower than
expected for the demo" while the run store already recorded
`stop_detail: max_calls (AGENTDESCENT_MAX_CALLS): 1 call(s) made, cap 1`. The
one surface a newcomer reads names the wrong cause and offers no knob.
"""

import io
import json
import os
from contextlib import redirect_stdout

from agentdescent import cli, runstore


def _run(tmp_path, monkeypatch, argv):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(["--store", str(tmp_path / "runs"), "demo",
                         "--dir", str(tmp_path / "work"), *argv])
    return code, buf.getvalue()


def _status(tmp_path):
    store = str(tmp_path / "runs")
    (run_id,) = os.listdir(store)
    return runstore.get(run_id, store=store).status()


def test_the_human_footer_names_the_cap_that_stopped_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "1")
    code, out = _run(tmp_path, monkeypatch, [])
    status = _status(tmp_path)
    assert code == 1, out
    assert status.stop_detail.startswith("max_calls"), status.stop_detail
    assert "max_calls" in out, out
    assert "cap 1" in out, out
    assert "lower than expected for the demo" not in out, out


def test_the_json_note_names_the_cap_that_stopped_the_run(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "1")
    code, out = _run(tmp_path, monkeypatch, ["--json"])
    payload = json.loads(out)
    assert code == 1 and payload["ok"] is False
    assert "max_calls" in payload["note"], payload["note"]
    assert "AGENTDESCENT_MAX_CALLS" in payload["note"], payload["note"]


def test_an_uncapped_demo_still_passes_and_carries_no_note(tmp_path, monkeypatch):
    code, out = _run(tmp_path, monkeypatch, ["--json"])
    payload = json.loads(out)
    assert code == 0, out
    assert payload["ok"] is True
    assert payload["final_reward"] == 1.0
    assert "note" not in payload


def test_the_footer_still_points_at_the_run_store(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_MAX_CALLS", "1")
    _code, out = _run(tmp_path, monkeypatch, [])
    assert "the run store has the detail" in out, out
    assert str(tmp_path / "runs") in out, out
