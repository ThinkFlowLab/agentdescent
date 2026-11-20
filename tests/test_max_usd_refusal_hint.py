"""An unpriced ``max_usd`` names the field to add, not a flag that cannot help (#1183).

``compose`` refuses a spec whose ``evolve`` block caps dollars without a
per-call price before ``cmd_evolve`` ever reads ``--usd-per-call``, so telling
the author to pass that flag sent them in a circle: the same sentence came back
at the same exit code. The price such a run can use lives in the spec.
"""

from __future__ import annotations

import json

import pytest

from agentdescent import cli
from agentdescent.evolvespec import EvolveSpec, SpecError, compose


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
