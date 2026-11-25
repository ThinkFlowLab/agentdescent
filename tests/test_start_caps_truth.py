"""`start.md`'s caps paragraph must not promise an uncapped run (#1268).

The page said that leaving both flags off makes "the run behave exactly as
before" — but ``AGENTDESCENT_MAX_CALLS`` clamps every run the process starts,
including one that names no cap of its own (``runstore._clamped_max_calls``,
plugin-design's "operator ceiling on model calls",
``tests/test_operator_run_cap.py``). A reader who believes the old sentence
plans a run the environment then stops early.

One assertion per claim, and the wrong-phrase assertion is negative: rewording
the paragraph is allowed, keeping the specific false promise is not.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
START = REPO_ROOT / "docs" / "start.md"

#: The sentence that is true and must survive verbatim: ``0`` is a limit, not
#: "unset" (``evolvespec._cap_value``, #1166).
ZERO_CAP_SENTENCE = (
    "`--max-calls 0` is a real limit — no calls at all — not \"unset\"."
)

#: The false promise the page carried until #1268.
FALSE_PROMISE = "behaves exactly as before"


def _caps_paragraph() -> str:
    """The paragraph that starts at the ``--max-calls 0`` sentence."""
    text = START.read_text(encoding="utf-8")
    start = text.index("`--max-calls 0` is a real limit")
    end = text.find("\n\n", start)
    return text[start:end if end != -1 else len(text)]


def test_the_caps_paragraph_does_not_promise_an_unchanged_run():
    para = _caps_paragraph()
    assert FALSE_PROMISE not in para, para


def test_the_caps_paragraph_states_that_no_cap_is_not_uncapped():
    para = _caps_paragraph()
    assert "AGENTDESCENT_MAX_CALLS" in para, para
    assert re.search(r"does not mean the run is\s+uncapped", para), para


def test_the_zero_cap_sentence_is_still_verbatim():
    """Control: the half of the paragraph that was already true stays as written."""
    assert ZERO_CAP_SENTENCE in _caps_paragraph()
