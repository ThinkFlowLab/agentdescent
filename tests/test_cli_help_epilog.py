"""Top-level ``--help`` ends with the next-steps block (#1174).

Since #1112 the listing, the usage ``{…}`` line and ``DEFAULT_SURFACE`` are
one first-run path.  Two verbs the first-run docs still walk a reader to,
``install`` and ``algorithms``, are advanced verbs there: they parse at the
top level but carry no help line, so they are invisible on the first screen.
The epilog is the pointer, not a second listing — it names those two
commands (and ``lab --help`` for the rest) and nothing else.
"""

import re

import pytest

from agentdescent import cli

EPILOG = """next steps:
  agentdescent install <host>      wire the skill + MCP server into a host
                                   (claude-code, dsh, codex, opencode, grok-bot)
  agentdescent algorithms list     the named algorithms a spec can ask for
                                   (show / run NAME PATH CASES)
  agentdescent lab --help          every other verb
"""

# Every command the epilog names, as argv it must accept.
EPILOG_COMMANDS = (
    ["install", "--help"],
    ["algorithms", "list", "--help"],
    ["lab", "--help"],
)


def _braces(text):
    m = re.search(r"\{([a-z_,-]+)\}", text)
    assert m, text
    return m.group(1).split(",")


def test_the_help_ends_with_the_next_steps_block():
    text = cli.build_parser().format_help()
    assert text.endswith(EPILOG), text


def test_the_epilog_names_the_two_commands_and_the_group():
    text = cli.build_parser().format_help()
    assert "agentdescent install <host>" in text
    assert "agentdescent algorithms list" in text
    assert "agentdescent lab --help" in text


@pytest.mark.parametrize("argv", EPILOG_COMMANDS,
                         ids=["install", "algorithms", "lab"])
def test_every_command_named_in_the_epilog_parses(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(argv)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_the_surface_and_the_usage_line_are_unchanged():
    # The epilog must not become a second listing (#1112).
    text = cli.build_parser().format_help()
    assert _braces(text) == list(cli.DEFAULT_SURFACE)
    assert list(cli.DEFAULT_SURFACE) == [
        "demo", "init", "plan", "evolve", "show", "apply",
        "doctor", "status", "lab", "mcp",
    ]


def test_the_epilog_stays_off_the_lab_and_run_help():
    sub = next(a for a in cli.build_parser()._actions if a.dest == "cmd")
    lab = sub.choices["lab"]
    assert "next steps:" not in lab.format_help()
    assert "next steps:" not in sub.choices["run"].format_help()
