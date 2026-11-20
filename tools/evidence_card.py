"""Evidence cards: the 12-field schema and its offline ``--check`` validator.

``#951`` publishes every empirical claim as a card that answers the same twelve
questions, so a reader can see what a claim leaves unanswered instead of
inferring it. No evidence is the explicit string ``not reviewed``; there is no
blank field and no omitted field. This module is the schema and the check; the
cards are later slices.

    python -m tools.evidence_card --check [CARD ...]

``--check`` validates ``*.json`` cards in the paths given, or ``reports/evidence``
when none is given (absent is ``0 cards``, not an error). Exit 0 valid, 1 refused
with one line per offending field, 2 input error. No network, no clock, and it
writes nothing.

A card says what reproduces it on a line starting ``command:`` inside one of the
twelve fields: an argv that resolves offline in this repository (``python -m
tools.evidence_card``, ``python scripts/x.py``, ``pytest tests/test_x.py``), or
``command: no offline command -- <why>`` when nothing here reproduces the claim.
Forcing a fake command is worse than none, so the second form is accepted with a
reason; a card that claims nothing -- all twelve fields ``not reviewed`` -- needs
neither, because it has nothing to reproduce.
"""
from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

SCHEMA_VERSION = 1

#: The twelve questions a card answers, in the order ``#951`` lists them.
FIELDS = ("held_out", "matched_budget", "cross_model", "cost", "disjoint_search",
          "reliability", "code", "evolved_artifact", "who_edits", "feedback",
          "timing", "topology")

#: The only way to say a field has no evidence; anything else non-empty is a value.
NOT_REVIEWED = "not reviewed"

DEFAULT_DIR = Path("reports") / "evidence"

#: The line inside a field that says what reproduces the card.
COMMAND_PREFIX = "command:"

#: The honest form for a claim no command in this repository reproduces.
NO_COMMAND = "no offline command"

#: A ``command:`` argv is resolved against the repository the cards live in.
ROOT = Path(__file__).resolve().parent.parent


def validate(card, source="card"):
    """Return the refusal lines for one card; empty means it satisfies v1."""
    if not isinstance(card, dict):
        return [f"{source}: a card must be a JSON object"]
    errors = []
    version = card.get("schema_version")
    if version is None:
        errors.append(f"{source}: schema_version: missing (expected {SCHEMA_VERSION})")
    elif isinstance(version, bool) or version != SCHEMA_VERSION:
        errors.append(f"{source}: schema_version: {version!r}, expected {SCHEMA_VERSION}")
    for name in FIELDS:
        if name not in card:
            errors.append(f"{source}: {name}: missing field")
        elif not isinstance(card[name], str):
            errors.append(f"{source}: {name}: not a string (use '{NOT_REVIEWED}')")
        elif not card[name].strip():
            errors.append(f"{source}: {name}: blank (use '{NOT_REVIEWED}')")
    # schema_version is metadata, not evidence: checked above, never one of the twelve.
    errors.extend(f"{source}: {name}: unknown field"
                  for name in card if name != "schema_version" and name not in FIELDS)
    errors.extend(_command_errors(card, source))
    return errors


def command_lines(card):
    """Return ``(field, value)`` for every ``command:`` marker in the card."""
    found = []
    for name in FIELDS:
        value = card.get(name)
        if not isinstance(value, str):
            continue
        for line in value.splitlines():
            line = line.strip()
            if line.startswith(COMMAND_PREFIX):
                found.append((name, line[len(COMMAND_PREFIX):].strip()))
    return found


def _module_exists(name):
    parts = [part for part in name.split(".") if part]
    if not parts or len(parts) != len(name.split(".")):
        return False
    base = ROOT.joinpath(*parts)
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _path_problems(targets):
    problems = []
    for target in targets:
        # ``tests/test_x.py::test_y`` is a node id; the file is the part to check.
        if not (ROOT / target.split("::")[0]).exists():
            problems.append(f"cannot resolve {target!r} offline (no such file)")
    return problems


def _argv_problems(argv):
    """Return one refusal fragment per argument that does not resolve offline."""
    runner = argv[0]
    if runner in ("python", "python3"):
        if len(argv) > 2 and argv[1] == "-m":
            module = argv[2]
            if module == "pytest":
                return _path_problems([a for a in argv[3:] if not a.startswith("-")])
            if not _module_exists(module):
                return [f"cannot resolve module {module!r} offline"]
            return []
        if len(argv) > 1 and not argv[1].startswith("-"):
            return _path_problems([argv[1]])
        return ["needs a script path or '-m <module>' after the interpreter"]
    if runner in ("pytest", "py.test"):
        # Only tokens that look like paths are checked: ``-k expr`` and ``-x``
        # are flags and their values, not files.
        return _path_problems([a for a in argv[1:]
                               if not a.startswith("-") and ("/" in a or a.endswith(".py"))])
    return [f"unsupported runner {runner!r} (use python, python3 or pytest)"]


def _command_errors(card, source):
    """The command rule: one line per card that does not say what reproduces it."""
    if all(card.get(name) == NOT_REVIEWED for name in FIELDS):
        return []  # a card that claims nothing has nothing to reproduce
    markers = command_lines(card)
    if not markers:
        return [f"{source}: command: missing (add 'command: <argv>' to a field, or "
                f"'command: {NO_COMMAND} -- <why>' when nothing here reproduces it)"]
    if len(markers) > 1:
        fields = ", ".join(name for name, _ in markers)
        return [f"{source}: command: given {len(markers)} times ({fields}); one is enough"]
    _, marker = markers[0]
    if marker.startswith(NO_COMMAND):
        reason = marker[len(NO_COMMAND):].strip()
        if not reason.startswith("--") or not reason[2:].strip():
            return [f"{source}: command: '{NO_COMMAND}' needs a reason after '--'"]
        return []
    try:
        argv = shlex.split(marker)
    except ValueError as exc:
        return [f"{source}: command: not a command line ({exc})"]
    if not argv:
        return [f"{source}: command: blank (an argv, or '{NO_COMMAND} -- <why>')"]
    return [f"{source}: command: {problem}" for problem in _argv_problems(argv)]


def collect(paths):
    """Return ``(cards, input_errors)``; only the implicit default directory is optional."""
    implicit = not paths
    cards, problems = [], []
    for raw in [DEFAULT_DIR] if implicit else paths:
        path = Path(raw)
        if path.is_dir():
            cards.extend(sorted(p for p in path.glob("*.json") if p.is_file()))
        elif path.is_file():
            cards.append(path)
        elif not (implicit and path == DEFAULT_DIR):
            problems.append(f"{path}: no such card or directory")
    return cards, problems


def _report(lines):
    for line in lines:
        print(f"error: {line}", file=sys.stderr)


def check(paths):
    """Validate the named cards and return the exit code."""
    cards, problems = collect(paths)
    if problems:
        _report(problems)
        return 2
    errors = []
    for path in cards:
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path}: not readable JSON ({exc})")
            continue
        errors.extend(validate(card, str(path)))
    if errors:
        _report(errors)
        return 1
    print(f"{len(cards)} card" if len(cards) == 1 else f"{len(cards)} cards")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m tools.evidence_card",
        description="Validate evidence cards against schema v1.",
    )
    parser.add_argument("--check", nargs="*", metavar="PATH",
                        help=f"cards or directories to check (default: {DEFAULT_DIR})")
    args = parser.parse_args(argv)
    if args.check is None:
        parser.print_usage(sys.stderr)
        return 2
    return check(args.check)


if __name__ == "__main__":
    sys.exit(main())
