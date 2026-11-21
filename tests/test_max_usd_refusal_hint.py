"""An unpriced ``max_usd`` names the field the caller can set (#1183, #1196).

``compose`` refuses a spec whose ``evolve`` block caps dollars without a
per-call price before ``cmd_evolve`` ever reads ``--usd-per-call``, so telling
the author to pass that flag sent them in a circle: the same sentence came back
at the same exit code. The price such a run can use lives in the spec.

The same rule then applies one surface at a time: a person typing the command
line can add ``--usd-per-call``, an MCP host can pass ``usd_per_call`` in the
same tool call, and a Python ``runstore.launch`` caller can do neither -- so the
builder's default names the field and no surface at all (#1196).
"""

from __future__ import annotations

import json

import pytest

from agentdescent import cli, runstore
from agentdescent.evolvespec import (EvolveSpec, SpecError, build_call_limit,
                                     compose)
from agentdescent.mcp import Tools

from tests.test_evolvespec import _dir_spec  # noqa: F401  (the MCP row's spec)

CLI_SENTENCE = (
    "max_usd needs usd_per_call: a dollar cap cannot be charged without "
    "a per-call price (pass --usd-per-call on the command line)")


def _spec(**evolve):
    return EvolveSpec(
        kind="text", target="You are a helpful assistant.",
        data={"inline": [{"prompt": "q0", "gold": "a0"}]},
        agent={"ref": "echo"}, evolve=evolve)


def test_an_unpriced_spec_dollar_cap_names_the_spec_field(tmp_path, capsys):
    """Refused with ``evolve.usd_per_call`` named, and no run store created."""
    with pytest.raises(SpecError) as caught:
        compose(_spec(max_usd=1))
    message = str(caught.value)
    assert "evolve.usd_per_call" in message, message
    assert "--usd-per-call" not in message, message

    path = tmp_path / "spec.json"
    path.write_text(json.dumps(_spec(max_usd=1).to_dict()), encoding="utf-8")
    code = cli.main(["--store", str(tmp_path / "runs"), "--json",
                     "evolve", str(path)])
    captured = capsys.readouterr().out
    refusal = json.loads(captured[captured.index("{"):])
    assert code == 2, code
    assert "evolve.usd_per_call" in refusal["error"], refusal
    assert not (tmp_path / "runs").exists(), "a refused spec created a run store"


def test_a_priced_spec_still_composes(tmp_path):
    """The pair still works, and an unpriced cap with no dollar limit is fine."""
    priced = compose(_spec(max_usd=1, usd_per_call=0.02))
    assert priced.call_limit.max_usd == 1.0, priced.call_limit
    assert priced.call_limit.usd_per_call == 0.02, priced.call_limit
    assert compose(_spec(max_calls=3)).call_limit.max_calls == 3


def test_the_command_line_keeps_its_flag_sentence(tmp_path, capsys):
    """A person can type the flag, so the CLI still names it, byte for byte.

    Asserted through the real command rather than against the helper's default,
    so a neutral default leaking into the CLI turns this red (#1196).
    """
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(_spec().to_dict()), encoding="utf-8")
    code = cli.main(["--store", str(tmp_path / "runs"), "--json",
                     "evolve", str(path), "--max-usd", "1"])
    captured = capsys.readouterr().out
    refusal = json.loads(captured[captured.index("{"):])
    assert code == 2, code
    assert refusal["error"] == CLI_SENTENCE, refusal["error"]


def test_a_tool_refusal_names_the_argument_it_can_pass(tmp_path, monkeypatch):
    """A host has no command line: the hint names ``usd_per_call`` (#1196).

    The sentence is asserted whole, not by "contains": the CLI row pins the
    shared base text, so an exact suffix is what makes a later reword on the
    tool path alone turn red instead of quietly passing.
    """
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("AGENTDESCENT_SURFACE_WRITE_DIRS", str(tmp_path))
    tool_sentence = (
        "max_usd needs usd_per_call: a dollar cap cannot be charged without "
        "a per-call price (usd_per_call in the same tool call)")
    t = Tools(str(tmp_path / "runs"))
    spec = _dir_spec(str(tmp_path)).to_dict()
    plan = t.plan(spec, max_usd=1.0)
    start = t.start(spec, max_usd=1.0)
    for payload in (plan, start):
        assert payload["ok"] is False, payload
        assert payload["error"] == tool_sentence, payload["error"]
    assert set(plan) == {"ok", "error"}, plan
    assert t.status()["runs"] == [], "a refused cap must not leave a run behind"


def test_a_python_caller_is_told_to_set_the_field_not_a_flag(tmp_path):
    """``runstore.launch`` is Python, so its hint names the field and no flag.

    No ``RunDir`` is built: the refusal comes before ``launch`` touches the
    store, which is exactly what makes "nothing was created" assertable (#1196).
    """
    store = tmp_path / "runs"
    with pytest.raises(runstore.RunStoreError) as caught:
        runstore.launch(store, max_usd=1.0)
    message = str(caught.value)
    assert "usd_per_call" in message, message
    assert "--usd-per-call" not in message, message
    assert not store.exists(), "a refused cap created a run store"


def test_the_default_hint_names_no_surface():
    """The default is what a caller we do not know yet inherits: no flag, no API.

    Teeth for the row above: if the default goes back to the CLI sentence, or
    grows any ``--`` flag, this turns red (#1196).
    """
    with pytest.raises(SpecError) as caught:
        build_call_limit(max_usd=1.0)
    message = str(caught.value)
    assert message.endswith("(set usd_per_call beside it)"), message
    assert "--" not in message, message
