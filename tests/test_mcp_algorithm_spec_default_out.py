"""An omitted ``out`` must land inside the write allowlist (#1108).

The tool description and the shared ``SKILL.md`` taught hosts to call
``algorithm_spec`` without ``out`` and get the starter spec *beside the target*.
That default is inside no default write root whenever the user's file sits
outside the server's cwd and ``$AGENTDESCENT_HOME``, so the shortest documented
path failed with ``ok=false`` on an untouched install (#1108). The default now
lands under ``$AGENTDESCENT_HOME`` (or the first explicit root), and the refusal
for an explicit ``out`` names the roots it can use.
"""

import json

from agentdescent.mcp import TOOL_DESCRIPTIONS, Tools

_FLAGS = dict(model="deepseek-v4-flash",
              base_url="https://ark.cn-beijing.volces.com/api/coding/v3")


def _prompt_and_cases(tmp_path, n=8):
    prompt = tmp_path / "prompt.md"
    prompt.write_text("be terse\n")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(n)))
    return prompt, cases


def _scratch(tmp_path, monkeypatch):
    """A server cwd and a user directory that are neither the home."""
    server = tmp_path / "server"
    user = tmp_path / "user-project"
    home = tmp_path / "home"
    server.mkdir()
    user.mkdir()
    monkeypatch.chdir(server)
    monkeypatch.delenv("AGENTDESCENT_SURFACE_WRITE_DIRS", raising=False)
    monkeypatch.setenv("AGENTDESCENT_HOME", str(home))
    return server, user, home


def test_an_omitted_out_lands_under_the_home_root(tmp_path, monkeypatch):
    _, user, home = _scratch(tmp_path, monkeypatch)
    prompt, cases = _prompt_and_cases(user)

    result = Tools(None).algorithm_spec(
        "rrsi", str(prompt), str(cases), **_FLAGS)

    assert result["ok"] is True, result
    expected = home / "agentdescent.rrsi.spec.json"
    assert result["spec_path"] == str(expected)
    assert json.loads(expected.read_text())["algorithm"] == "rrsi"
    # The documented default never touches the user's directory.
    assert not (user / "agentdescent.rrsi.spec.json").exists()


def test_an_omitted_out_honours_an_explicit_allowlist(tmp_path, monkeypatch):
    _, user, _ = _scratch(tmp_path, monkeypatch)
    prompt, cases = _prompt_and_cases(user)
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    result = Tools(None, surface_write_dirs=(str(allowed),)).algorithm_spec(
        "rrsi", str(prompt), str(cases), **_FLAGS)

    assert result["ok"] is True, result
    expected = allowed / "agentdescent.rrsi.spec.json"
    assert result["spec_path"] == str(expected)
    assert expected.exists()


def test_an_explicit_out_outside_the_allowlist_names_where_it_may_write(
        tmp_path, monkeypatch):
    _, user, _ = _scratch(tmp_path, monkeypatch)
    prompt, cases = _prompt_and_cases(user)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside" / "spec.json"

    result = Tools(None, surface_write_dirs=(str(allowed),)).algorithm_spec(
        "rrsi", str(prompt), str(cases), out=str(outside), **_FLAGS)

    assert result["ok"] is False
    error = result["error"]
    assert "write allowlist" in error
    # Actionable: the roots it may use and an example path under one of them.
    assert str(allowed) in error
    assert "pass `out`" in error
    assert not outside.exists()


def test_an_empty_allowlist_says_so_instead_of_naming_a_target_directory(
        tmp_path, monkeypatch):
    _, user, _ = _scratch(tmp_path, monkeypatch)
    prompt, cases = _prompt_and_cases(user)

    result = Tools(None, surface_write_dirs=()).algorithm_spec(
        "rrsi", str(prompt), str(cases), **_FLAGS)

    assert result["ok"] is False
    assert "AGENTDESCENT_SURFACE_WRITE_DIRS" in result["error"]
    assert "no write" in result["error"].lower()


def test_the_description_no_longer_documents_a_beside_the_target_default():
    text = TOOL_DESCRIPTIONS["algorithm_spec"]

    assert "beside the target" not in text
    assert "AGENTDESCENT_HOME" in text


def test_the_shared_skill_writes_the_default_spec_under_the_home():
    from agentdescent.integrations import _skill_body

    body = _skill_body()

    assert "beside the target" not in body
    assert "AGENTDESCENT_HOME" in body
