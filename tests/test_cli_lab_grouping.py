"""The default ``--help`` is one first-run path; every verb also runs under ``lab`` (#1112).

Thirty-odd verbs are all registered at the top level, so a new user's first
screen is a wall of ``portfolio`` / ``campaign`` / ``tenant``.  The fix keeps
every verb reachable under its old name and mounts the same declarations a
second time under a ``lab`` group, while the default listing shows only the
first-run surface.

What is pinned here:

* the verbs ``agentdescent --help`` lists, in order, and the same set in the
  usage line;
* ``lab`` holding every verb but itself, so ``agentdescent lab <verb>`` is
  reachable for all of them, not only the advanced ones;
* the two paths parsing to the same dispatch (``fn``) and the same namespace
  for every verb -- a grouping change may not alter a single argument;
* each advanced verb still answering ``--help`` at its old path.
"""

import argparse
import re

import pytest

from agentdescent import cli


def _subparsers(parser):
    return next(a for a in parser._actions
                if isinstance(a, argparse._SubParsersAction))


def _top_level():
    return _subparsers(cli.build_parser())


def _braced_verbs(text):
    """The ``{a,b,c}`` command list argparse prints, as a list."""
    match = re.search(r"\{([a-z_,-]+)\}", text)
    assert match, text
    return match.group(1).split(",")


def _listed_verbs(text):
    """The verbs under ``positional arguments:``, in the order help shows them."""
    return re.findall(r"^    ([a-z][a-z_-]*)\s{2,}\S", text, re.M)


#: What a first run needs, in the order argparse lists them (registration order).
DEFAULT_SURFACE = [
    "demo", "init", "plan", "evolve", "status", "show", "apply", "doctor",
    "lab", "mcp",
]

#: Every verb mounted under ``lab``: everything registered but ``lab`` itself.
_VERBS = [n for n in _top_level().choices if n != "lab"]
_ADVANCED = [n for n in _VERBS if n not in DEFAULT_SURFACE]


def test_default_help_lists_only_the_first_run_surface():
    text = cli.build_parser().format_help()
    assert _listed_verbs(text) == DEFAULT_SURFACE, text


def test_the_usage_line_names_the_same_surface():
    assert _braced_verbs(cli.build_parser().format_usage()) == DEFAULT_SURFACE


def test_lab_mounts_every_verb_but_itself():
    top = _top_level()
    lab = _subparsers(top.choices["lab"])
    assert list(lab.choices) == _VERBS


def test_advanced_verbs_are_hidden_but_still_parsed():
    parser = cli.build_parser()
    assert "campaign" not in _listed_verbs(parser.format_help())
    names = _subparsers(parser).choices
    assert "campaign" in names and "tenant" in names and "serve" in names


def _value_for(action):
    if action.choices:
        return str(next(iter(action.choices)))
    if action.type is int:
        return "1"
    if action.type is float:
        return "1.5"
    return "x"


def _minimal_args(parser):
    """A shortest argv that satisfies one verb's required arguments."""
    argv = []
    for group in parser._mutually_exclusive_groups:
        if not group.required:
            continue
        action = group._group_actions[0]
        argv.append(action.option_strings[-1])
        if action.nargs != 0:
            argv.append(_value_for(action))
    nested = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            nested = action
            continue
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if action.option_strings:
            if not action.required:
                continue
            argv.append(action.option_strings[-1])
            if action.nargs != 0:
                argv.append(_value_for(action))
        elif action.nargs in (None, "+"):
            argv.append(_value_for(action))
    if nested is not None:
        name = next(iter(nested.choices))
        argv.append(name)
        argv += _minimal_args(nested.choices[name])
    return argv


def _namespace(args):
    # ``cmd`` is the top-level dispatch key and ``lab_cmd`` the nested one;
    # both name where the verb was typed, so only they may differ.
    return {k: v for k, v in vars(args).items()
            if k not in ("fn", "cmd", "lab_cmd")}


@pytest.mark.parametrize("verb", _VERBS)
def test_lab_path_parses_like_the_top_level(verb):
    parser = cli.build_parser()
    argv = [verb] + _minimal_args(_subparsers(parser).choices[verb])
    at_top = parser.parse_args(argv)
    at_lab = parser.parse_args(["lab"] + argv)
    assert at_top.fn is not None
    assert at_lab.fn is at_top.fn
    assert _namespace(at_lab) == _namespace(at_top)


@pytest.mark.parametrize("verb", _ADVANCED)
def test_a_hidden_verb_still_answers_help(verb, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([verb, "--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip()


@pytest.mark.parametrize("verb", _ADVANCED)
def test_the_lab_path_answers_help(verb, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["lab", verb, "--help"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip()
