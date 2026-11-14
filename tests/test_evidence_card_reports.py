"""The published evidence cards in ``reports/evidence`` stay complete (#951).

``tools/evidence_card`` is the schema and the checker; these tests pin the
cards that are actually published, so a claim cannot ship a card with a blank
or missing field and the #1042 leaf-write-through card keeps naming the code
and the regression test a reader needs to re-run it.

Two of the cards are headline results from ``reports/`` -- the audit's constant
rubric tying the judge, and the 177-pair verifier bias. Their fields are facts
about files in this repository, so they are pinned here rather than trusted.
"""
import json
from pathlib import Path

import pytest

from tools import evidence_card

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "reports" / "evidence"

#: The cards that carry a headline result a reader is meant to check.
HEADLINE_CARDS = ("audit-always-no-ties-the-judge.json",
                  "audit-177-pair-verifier-bias.json")


def _published():
    return sorted(EVIDENCE.glob("*.json"))


def test_the_repo_publishes_at_least_one_card():
    assert _published(), f"no evidence card under {EVIDENCE}"


def test_every_published_card_satisfies_schema_v1():
    for card_path in _published():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        assert evidence_card.validate(card, card_path.name) == [], card_path.name


def test_the_1042_card_names_its_code_and_its_regression_test():
    card_path = EVIDENCE / "1042-ports-leaf-write-through.json"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    assert "a095a6504b92b5788c7228649577b6241a0c2939" in card["code"]
    assert "agentdescent/ports.py:97" in card["code"]
    assert "tests/test_ports_symlink_leaf.py" in card["code"]
    assert card["held_out"] == "not reviewed"


def test_the_1042_card_is_refused_by_name_when_a_field_is_removed(tmp_path, capsys):
    card = json.loads((EVIDENCE / "1042-ports-leaf-write-through.json")
                      .read_text(encoding="utf-8"))
    del card["held_out"]
    path = tmp_path / "card.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    assert evidence_card.main(["--check", str(path)]) == 1
    err = capsys.readouterr().err
    assert "held_out" in err and "missing field" in err


def test_the_repo_publishes_a_card_for_more_than_one_headline_result():
    published = {path.name for path in _published()}
    missing = [name for name in HEADLINE_CARDS if name not in published]
    assert not missing, f"no evidence card for {missing} under {EVIDENCE}"


@pytest.mark.parametrize("name", HEADLINE_CARDS)
def test_a_headline_card_quotes_the_number_it_is_about(name):
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    # The two claims rest on numbers that exist in this repository: the audit
    # records and the report computed from them. A card that loses its number
    # is a card a reader cannot check.
    needles = ("0.836",) if name == HEADLINE_CARDS[0] else ("31 of 177", "0.2203")
    for needle in needles:
        assert needle in text, f"{name} does not quote {needle!r}"
    assert "3a5d5513bbfea71b75911add4fd0aa4854177e49" in text, name


@pytest.mark.parametrize("name", HEADLINE_CARDS)
def test_a_headline_card_names_a_test_that_exists(name):
    """A card's reproduction has to point at something a reader can run."""
    card = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
    text = card["code"] + card["reliability"]
    named = [token.split(":")[0] for token in text.split()
             if token.startswith("tests/") and token.split(":")[0].endswith(".py")]
    assert named, f"{name} names no test file"
    for path in named:
        assert (REPO / path).is_file(), f"{name} names missing test {path}"


def test_every_published_card_writes_absent_evidence_as_not_reviewed():
    for card_path in _published():
        card = json.loads(card_path.read_text(encoding="utf-8"))
        for field in evidence_card.FIELDS:
            value = card[field]
            if value == evidence_card.NOT_REVIEWED:
                continue
            # Anything not "not reviewed" has to say something, and every one of
            # the cards here starts its answer with a sentence, not a dash.
            assert len(value.split()) >= 5, f"{card_path.name}: {field} is a stub"


def test_the_policy_that_a_new_claim_needs_a_card_is_published():
    """#951 expresses the rule as a docs sentence, not as a PR-template edit."""
    readme = EVIDENCE / "README.md"
    assert readme.is_file(), f"no {readme}"
    text = readme.read_text(encoding="utf-8")
    assert "A new claim needs a card" in text
    assert "not reviewed" in text
