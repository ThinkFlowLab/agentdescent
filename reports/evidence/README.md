# Evidence cards

One card per empirical claim, twelve questions, machine-checkable. The schema
and its checker are `tools/evidence_card.py`; the twelve fields are the ones
`#951` lists, and the only way to say a field has no evidence is the string
`not reviewed`.

**A new claim needs a card.** Any pull request, report or doc page that adds a
headline result adds a card here in the same change. The card is what a reader
uses to see the gap: a field reading `not reviewed` is a statement that nobody
measured it, which is more useful than the claim not saying so.

Every card is checked in CI, and `tests/test_evidence_card_reports.py` pins each
published card's own anchors — the numbers it quotes and the test that
reproduces them — so a card cannot drift away from the result it describes.

```sh
python -m tools.evidence_card --check          # every card in this directory
python -m tools.evidence_card --check <card>   # one card
```

Exit 0 valid, 1 refused with one line per offending field, 2 input error. A
missing field, an unknown field, a blank value or a non-string value is refused
by name; `schema_version` must be `1`.
