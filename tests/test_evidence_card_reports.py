"""The published evidence cards in ``reports/evidence`` stay complete (#951).

``tools/evidence_card`` is the schema and the checker; these tests pin the
cards that are actually published, so a claim cannot ship a card with a blank
or missing field and the #1042 leaf-write-through card keeps naming the code
and the regression test a reader needs to re-run it.
"""
import json
from pathlib import Path

from tools import evidence_card

REPO = Path(__file__).resolve().parent.parent
EVIDENCE = REPO / "reports" / "evidence"


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
