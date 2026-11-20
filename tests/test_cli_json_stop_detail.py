"""`--json evolve` and `--json show` say which cap stopped the run (#1190).

``status.json`` and the human status line carry ``stop_detail`` (#1166), but the
machine output of the two commands that end or report a run dropped it: a
caller reading ``"stop_reason": "budget"`` could not tell the operator ceiling
from its own ``--max-calls``. The key is additive: a run with no cap set must
produce exactly yesterday's payload, so the absent row below is the guard
against a blanket ``None``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from agentdescent import cli
from agentdescent.evolvespec import EvolveSpec

#: One entry per model call the spec's agent actually makes.
CALLS = []


def counting_agent(*, usage=None, tag="agent"):
    """A spec-nameable model factory that records each call."""

    def complete(prompt):
        CALLS.append(tag)
        return "ok"

    return complete


def _spec():
    model = {"ref": "tests.test_cli_json_stop_detail:counting_agent", "tag": "agent"}
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": f"q{i}", "gold": f"a{i}"} for i in range(8)]},
        agent=model, reflect=model, allow=["tests."],
        evolve={"rounds": 4, "n_workers": 4, "seed": 0, "patience": 10})


def _cli(*args):
    """Run the CLI in-process; returns (exit code, stdout)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = cli.main(list(args))
    return code, buf.getvalue()


def _evolve_json(tmp_path, *, max_calls=None):
    CALLS.clear()
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(_spec().to_dict()))
    args = ["--store", str(tmp_path / "runs"), "--json", "evolve", str(path)]
    if max_calls is not None:
        args += ["--max-calls", str(max_calls)]
    code, out = _cli(*args)
    assert code == 0, out
    return json.loads(out)


def _show_json(tmp_path, run_id):
    code, out = _cli("--store", str(tmp_path / "runs"), "--json", "show", run_id)
    assert code == 0, out
    return json.loads(out)


def test_evolve_json_omits_stop_detail_without_a_cap(tmp_path):
    payload = _evolve_json(tmp_path)
    assert payload["stop_reason"] != "budget", payload
    assert "stop_detail" not in payload, payload


def test_evolve_json_names_the_limit_that_fired(tmp_path):
    payload = _evolve_json(tmp_path, max_calls=1)
    assert payload["stop_reason"] == "budget", payload
    assert "max_calls" in payload["stop_detail"], payload


def test_show_json_omits_stop_detail_without_a_cap(tmp_path):
    payload = _evolve_json(tmp_path)
    shown = _show_json(tmp_path, payload["run_id"])
    assert shown["stop_reason"] != "budget", shown
    assert "stop_detail" not in shown, shown


def test_show_json_names_the_limit_that_fired(tmp_path):
    payload = _evolve_json(tmp_path, max_calls=1)
    shown = _show_json(tmp_path, payload["run_id"])
    assert shown["stop_reason"] == "budget", shown
    assert "max_calls" in shown["stop_detail"], shown
