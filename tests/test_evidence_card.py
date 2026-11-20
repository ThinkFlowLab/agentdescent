"""Evidence cards: the 12-field schema and its offline ``--check`` validator.

``#951`` publishes every claim as a card, so a reader can see which of the twelve
questions it leaves unanswered. These pin the validator on temporary trees: a
complete card passes, every incomplete one is refused with the offending field
named on one line, and ``not reviewed`` is the explicit "no evidence".
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FIELDS = ("held_out", "matched_budget", "cross_model", "cost", "disjoint_search",
          "reliability", "code", "evolved_artifact", "who_edits", "feedback",
          "timing", "topology")

#: An argv the checker resolves offline in this checkout.
COMMAND = "python -m tools.evidence_card --check"


def _tool():
    from tools import evidence_card
    return evidence_card


def _stamp(card):
    """Give the card its ``command:`` line, in a field the test is not about."""
    if any("command:" in value for value in card.values() if isinstance(value, str)):
        return card
    for name in ("code", "timing", "topology"):
        value = card.get(name)
        if isinstance(value, str) and value.strip() and value != "not reviewed":
            card[name] = f"{value}\ncommand: {COMMAND}"
            return card
    return card


def _card(**overrides):
    card = {name: f"{name} measured" for name in FIELDS}
    card["schema_version"] = 1
    card.update(overrides)
    return _stamp(card)


def _write(tmp_path, card, name="card.json"):
    path = tmp_path / name
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


def _check(*paths):
    return _tool().main(["--check", *[str(p) for p in paths]])


def test_a_complete_card_passes(tmp_path, capsys):
    assert _check(_write(tmp_path, _card())) == 0
    assert "1 card" in capsys.readouterr().out


@pytest.mark.parametrize("field", FIELDS)
def test_a_missing_field_is_refused_by_name(tmp_path, capsys, field):
    card = _card()
    del card[field]
    _stamp(card)  # keep the command rule out of what this test asserts
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert field in err
    assert "\n" not in err.strip(), "a refusal is one line per offending field"


@pytest.mark.parametrize("value, needle", [("", "blank"), (None, "string")])
def test_a_blank_or_non_string_value_is_refused_by_name(tmp_path, capsys, value, needle):
    assert _check(_write(tmp_path, _card(cost=value))) == 1
    err = capsys.readouterr().err
    assert "cost" in err and needle in err


@pytest.mark.parametrize("field", FIELDS)
def test_not_reviewed_is_accepted_for_every_field(tmp_path, field):
    assert _check(_write(tmp_path, _card(**{field: "not reviewed"}))) == 0


def test_a_card_of_all_not_reviewed_passes(tmp_path, capsys):
    card = {name: "not reviewed" for name in FIELDS}
    card["schema_version"] = 1
    assert _check(_write(tmp_path, card)) == 0
    assert "1 card" in capsys.readouterr().out


def test_an_unknown_field_is_refused_by_name(tmp_path, capsys):
    assert _check(_write(tmp_path, _card(confidence="high"))) == 1
    err = capsys.readouterr().err
    assert "confidence" in err and "unknown" in err


@pytest.mark.parametrize("version", [2, 0, "1"])
def test_a_wrong_schema_version_is_refused_by_name(tmp_path, capsys, version):
    assert _check(_write(tmp_path, _card(schema_version=version))) == 1
    assert "schema_version" in capsys.readouterr().err


def test_one_bad_card_fails_the_run_and_names_it(tmp_path, capsys):
    _write(tmp_path, _card(), "good.json")
    bad = _card()
    del bad["timing"]
    _write(tmp_path, bad, "bad.json")
    assert _check(tmp_path) == 1
    err = capsys.readouterr().err
    assert "bad.json" in err and "timing" in err


def test_no_paths_without_the_directory_is_zero_cards(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _tool().main(["--check"]) == 0
    assert "0 cards" in capsys.readouterr().out
    assert not (tmp_path / "reports" / "evidence").exists(), "the check writes nothing"


def test_no_paths_scans_the_default_directory(tmp_path, monkeypatch, capsys):
    evidence = tmp_path / "reports" / "evidence"
    evidence.mkdir(parents=True)
    _write(evidence, _card())
    monkeypatch.chdir(tmp_path)
    assert _tool().main(["--check"]) == 0
    assert "1 card" in capsys.readouterr().out


# -- the command rule: a card says what reproduces it ------------------------

def test_a_card_with_no_command_line_is_refused_by_name(tmp_path, capsys):
    card = _card()
    card["code"] = "code measured"
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert "command" in err and "missing" in err
    assert "\n" not in err.strip(), "a refusal is one line per offending field"


def test_the_command_line_may_live_in_any_field(tmp_path):
    card = _card()
    card["code"] = "code measured"
    card["topology"] = f"topology measured\ncommand: {COMMAND}"
    assert _check(_write(tmp_path, card)) == 0


def test_no_offline_command_is_accepted_with_a_reason(tmp_path):
    card = _card()
    card["code"] = ("code measured\ncommand: no offline command -- the run needs "
                    "a live model")
    assert _check(_write(tmp_path, card)) == 0


def test_no_offline_command_without_a_reason_is_refused(tmp_path, capsys):
    card = _card()
    card["code"] = "code measured\ncommand: no offline command"
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert "reason" in err
    assert "\n" not in err.strip(), "a refusal is one line per offending field"


@pytest.mark.parametrize("command, needle", [
    ("python -m nope.not_here --check", "cannot resolve module"),
    ("python scripts/nope.py", "cannot resolve"),
    ("pytest tests/nope.py", "cannot resolve"),
    ("cargo bench", "unsupported runner"),
])
def test_a_command_that_does_not_resolve_is_refused(tmp_path, capsys, command, needle):
    card = _card()
    card["code"] = f"code measured\ncommand: {command}"
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert needle in err and "command" in err
    assert "\n" not in err.strip(), "a refusal is one line per offending field"


def test_two_command_lines_are_refused(tmp_path, capsys):
    card = _card()
    card["timing"] = f"timing measured\ncommand: {COMMAND}"
    assert _check(_write(tmp_path, card)) == 1
    err = capsys.readouterr().err
    assert "2 times" in err and "code, timing" in err


def test_the_module_is_runnable_with_dash_m(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "tools.evidence_card", "--check",
         str(_write(tmp_path, _card()))],
        cwd=str(REPO), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "1 card" in proc.stdout
