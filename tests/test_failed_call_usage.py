"""Tokens a provider charged on a *failed* call must not vanish (#1202).

A failed call already records its wall-clock (``Usage.failure_seconds``) but not
the tokens the provider reported -- and a 4xx body or a stream that dies after
the last chunk can carry ``usage``. That is money already spent, so it lands in
the ordinary counters (and therefore in the ``max_tokens`` meter), while the
report keeps it visible as its own column:

- ``failed_usage_attempts`` / ``failed_usage_tokens`` count only failures that came
  with usage numbers; a failure without them records **0** tokens and is only a
  failed call.
- The accumulation happens in the same ``record()`` call that adds the tokens,
  so the failure column and the totals cannot drift apart.

Both fields are additive with defaults: an old ``Usage`` payload that lacks them
loads unchanged.
"""

import io
import json
import urllib.error

import pytest

from agentdescent.agents import (
    AgentError, Usage, claude, cli_agent, openai_compatible,
)


def _http_error(body, code=429, url="https://api.example/v1/chat/completions"):
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(body.encode()))


def _openai_ok(monkeypatch, *, prompt=10, completion=20, calls=None):
    """urlopen that answers 200 with a well-formed chat completion."""
    def urlopen(req, timeout=None):
        if calls is not None:
            calls.append(req)
        body = {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}
        return io.BytesIO(json.dumps(body).encode())
    monkeypatch.setattr("agentdescent.agents.urllib.request.urlopen", urlopen)


def _openai_error(monkeypatch, body, code=429):
    def urlopen(req, timeout=None):
        raise _http_error(body, code=code, url=req.full_url)
    monkeypatch.setattr("agentdescent.agents.urllib.request.urlopen", urlopen)


# --- the two new fields ----------------------------------------------------

def test_a_failed_call_with_reported_usage_counts_in_totals_and_in_its_own_column():
    u = Usage()
    u.record(prompt_tokens=40, completion_tokens=60, seconds=1.0,
             failed=True, reported_usage=True)
    assert (u.prompt_tokens, u.completion_tokens) == (40, 60)
    assert u.total_tokens == 100
    assert u.failures == 1
    assert u.failed_usage_attempts == 1
    assert u.failed_usage_tokens == 100


def test_a_failed_call_without_usage_records_zero_tokens():
    u = Usage()
    u.record(seconds=2.0, failed=True)
    assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (0, 0, 0)
    assert u.failures == 1
    assert u.failed_usage_attempts == 0
    assert u.failed_usage_tokens == 0


def test_a_successful_call_records_the_same_numbers_as_today():
    u = Usage()
    u.record(prompt_tokens=10, completion_tokens=20, seconds=0.5)
    assert u.total_tokens == 30
    assert u.failures == 0 and u.failed_usage_attempts == 0


def test_the_failure_column_is_a_subset_of_the_totals_not_a_parallel_tally():
    u = Usage()
    u.record(prompt_tokens=40, completion_tokens=60, failed=True,
             reported_usage=True)
    u.record(seconds=0.1, failed=True)          # no usage: failure only
    assert u.failures == 2
    assert u.failed_usage_attempts == 1
    assert u.failed_usage_tokens <= u.total_tokens == 100
    # Direct ``Usage`` path only: every provider record is also a call here.
    # The sink path counts attempts instead, so this bound does not hold there.
    assert u.failed_usage_attempts <= u.calls


# --- the two body-reading sites -------------------------------------------

def test_an_openai_error_body_with_usage_records_them_and_still_raises(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = json.dumps({"error": {"message": "boom"},
                       "usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    _openai_error(monkeypatch, body, code=429)
    u = Usage()
    call = openai_compatible("m", usage=u, retries=0)
    with pytest.raises(Exception) as raised:
        call("hi")
    assert "boom" in str(raised.value)
    assert (u.prompt_tokens, u.completion_tokens) == (7, 3)
    assert u.failures == 1 and u.failed_usage_attempts == 1
    assert u.failed_usage_tokens == 10


def test_an_error_body_without_usage_is_only_a_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _openai_error(monkeypatch, json.dumps({"error": {"message": "rate limit"}}))
    u = Usage()
    call = openai_compatible("m", usage=u, retries=0)
    with pytest.raises(Exception):
        call("hi")
    assert u.total_tokens == 0
    assert u.failures == 1 and u.failed_usage_attempts == 0


def test_the_detail_stops_at_400_bytes_while_usage_parses_from_the_whole_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    padding = "x" * 600
    body = json.dumps({"error": {"message": padding},
                       "usage": {"prompt_tokens": 5, "completion_tokens": 6}})
    _openai_error(monkeypatch, body)
    u = Usage()
    call = openai_compatible("m", usage=u, retries=0)
    with pytest.raises(Exception) as raised:
        call("hi")
    message = str(raised.value)
    assert padding[:400] not in message.split(": ", 1)[-1][:400] + "zzz"
    assert len(message.split(": ", 1)[-1]) <= 400
    assert u.failed_usage_tokens == 11


def test_an_anthropic_error_body_with_usage_records_input_and_output(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    body = json.dumps({"type": "error",
                       "usage": {"input_tokens": 8, "output_tokens": 2}})
    def urlopen(req, timeout=None):
        raise _http_error(body, code=500, url=req.full_url)
    monkeypatch.setattr("agentdescent.agents.urllib.request.urlopen", urlopen)
    u = Usage()
    from agentdescent.agents import anthropic_compatible
    call = anthropic_compatible("m", usage=u, retries=0)
    with pytest.raises(Exception):
        call("hi")
    assert (u.prompt_tokens, u.completion_tokens) == (8, 2)
    assert u.failed_usage_attempts == 1


def test_a_caller_without_usage_gets_the_same_error_text(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = json.dumps({"error": {"message": "quota"}})
    _openai_error(monkeypatch, body, code=400)
    calls, texts = [], []
    for usage in (None, Usage()):
        calls.append(openai_compatible("m", usage=usage, retries=0))
        with pytest.raises(Exception) as raised:
            calls[-1]("hi")
        texts.append(str(raised.value))
    assert texts[0] == texts[1]
    assert "quota" in texts[0]


def test_a_stream_that_dies_after_usage_still_counts_the_tokens(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    def urlopen(req, timeout=None):
        def frames():
            yield b'data: {"usage": {"prompt_tokens": 9, "completion_tokens": 1}}\n\n'
            raise RuntimeError("connection reset")
        class _Resp:
            def __enter__(self):
                return frames()
            def __exit__(self, *exc):
                return False
        return _Resp()
    monkeypatch.setattr("agentdescent.agents.urllib.request.urlopen", urlopen)
    u = Usage()
    call = openai_compatible("m", usage=u, retries=0, stream=True)
    with pytest.raises(Exception):
        call("hi")
    assert (u.prompt_tokens, u.completion_tokens) == (9, 1)
    assert u.failures == 1 and u.failed_usage_attempts == 1


def test_top_level_usage_and_junk_counts_are_ignored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = json.dumps({"usage": {"prompt_tokens": "12", "completion_tokens": -5}})
    _openai_error(monkeypatch, body)
    u = Usage()
    with pytest.raises(Exception):
        openai_compatible("m", usage=u, retries=0)("hi")
    assert u.total_tokens == 0 and u.failed_usage_attempts == 0


def test_the_subprocess_and_sdk_paths_add_no_tokens(monkeypatch):
    u = Usage()
    with pytest.raises(AgentError):
        cli_agent(["sh", "-c", "exit 3"], usage=u)("hi")
    assert u.failures == 1 and u.total_tokens == 0

    class _Messages:
        def create(self, **kw):
            raise RuntimeError("sdk boom")
    class _Client:
        messages = _Messages()
    u2 = Usage()
    with pytest.raises(RuntimeError):
        claude("m", usage=u2, client=_Client(), retries=0)("hi")
    assert u2.failures == 1 and u2.total_tokens == 0


# --- additive fields and the report ---------------------------------------

def test_an_old_usage_payload_without_the_new_fields_loads_with_defaults():
    old = {"calls": 2, "prompt_tokens": 3, "completion_tokens": 4,
           "seconds": 1.0, "failures": 1, "failure_seconds": 0.5}
    u = Usage(**json.loads(json.dumps(old)))       # round-trips through JSON
    assert (u.failed_usage_attempts, u.failed_usage_tokens) == (0, 0)
    assert u.total_tokens == 7
    # An old fixture prints the same numbers it printed before the fields.
    assert u.summary() == Usage(**old).summary()


def test_the_summary_separates_failures_that_reported_usage():
    u = Usage()
    u.record(prompt_tokens=40, completion_tokens=60, failed=True,
             reported_usage=True)
    u.record(seconds=0.1, failed=True)
    summary = u.summary()
    assert "2 failed" in summary
    assert "100" in summary and "1" in summary
    assert u.failed_usage_tokens <= u.total_tokens


def test_a_failed_call_with_usage_moves_the_token_meter_earlier():
    """The tokens of a failed call are money spent: the cap must see them.

    Two runs of the same two-round shape; the first call fails at the provider.
    With usage on the failure the ``max_tokens`` meter trips; without usage the
    same run stays under the cap -- that is the whole difference (#1202).
    """
    import warnings

    from agentdescent.evolution import Task, evolve

    def _run(failure: str):
        u = Usage()
        state = {"failed": False}

        class _Agent:
            def solve(self, rendered, task):
                if not state["failed"]:
                    state["failed"] = True
                    if failure == "usage":
                        u.record(prompt_tokens=1_000_000, failed=True,
                                 reported_usage=True)
                    else:
                        u.record(failed=True)
                    raise RuntimeError("429 from the provider")
                u.record(prompt_tokens=100, completion_tokens=200)
                return task.id

            def propose(self, rendered, task, output, reward):
                u.record(prompt_tokens=100, completion_tokens=200)
                return None

        tasks = [Task(id=f"t{i}", prompt=f"task {i}") for i in range(8)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = evolve(tasks, lambda t, o: 0.5, agent=_Agent(), rounds=2,
                            n_workers=1, max_tokens=5_000, usage=u,
                            asynchronous=False)
        return result, u

    metered, usage_metered = _run("usage")
    unmetered, usage_unmetered = _run("none")
    assert usage_metered.failed_usage_attempts == 1
    assert usage_unmetered.failed_usage_attempts == 0
    assert metered.stop_reason == "max_tokens"
    assert unmetered.stop_reason != "max_tokens"


def test_a_sink_records_the_failed_column_without_double_counting(monkeypatch):
    """Spec runs hand the adapter a sink, so the column needs a sink path.

    ``add_tokens`` already added the tokens; the failure column must be bumped
    without adding them twice, and the sink must not count a call.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = json.dumps({"error": {"message": "boom"},
                       "usage": {"prompt_tokens": 40, "completion_tokens": 60}})
    _openai_error(monkeypatch, body)
    u = Usage()
    call = openai_compatible("m", usage=u.token_sink(), retries=0)
    with pytest.raises(Exception):
        call("hi")
    assert u.calls == 0, "the sink must not count a call"
    assert u.total_tokens == 100
    assert u.failed_usage_attempts == 1
    assert u.failed_usage_tokens == 100
    # The sink path has no call counter behind it, so only the subset holds.
    assert u.failed_usage_tokens <= u.total_tokens


def test_one_retried_call_can_report_several_usage_bearing_attempts(monkeypatch):
    """On the sink path the column counts attempts, which may exceed calls."""
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    body = json.dumps({"usage": {"prompt_tokens": 10, "completion_tokens": 0}})
    _openai_error(monkeypatch, body, code=503)
    u = Usage()
    call = openai_compatible("m", usage=u.token_sink(), retries=2)
    with pytest.raises(Exception):
        call("hi")
    assert u.calls == 0
    assert u.failed_usage_attempts >= 2
    assert u.failed_usage_tokens == 10 * u.failed_usage_attempts
    assert u.failed_usage_tokens <= u.total_tokens


def test_the_saved_run_summary_carries_the_new_counters(tmp_path):
    """The JSON summary lists them, so they are not visible only in summary().

    The keys are additive: a reader that knows the old five still works, which
    the second assertion pins.
    """
    import warnings

    from agentdescent.evolution import Task, evolve

    u = Usage()
    state = {"failed": False}

    class _Agent:
        def solve(self, rendered, task):
            if not state["failed"]:
                state["failed"] = True
                u.record(prompt_tokens=40, completion_tokens=60, failed=True,
                         reported_usage=True)
                raise RuntimeError("429")
            u.record(prompt_tokens=10, completion_tokens=20)
            return task.id

        def propose(self, rendered, task, output, reward):
            u.record(prompt_tokens=10, completion_tokens=20)
            return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = evolve([Task(id=f"t{i}", prompt="p") for i in range(4)],
                        lambda t, o: 0.5, agent=_Agent(), rounds=1, n_workers=1,
                        usage=u, asynchronous=False)
    out = tmp_path / "run.json"
    result.save(str(out))
    usage = json.loads(out.read_text())["usage"]
    assert usage["failed_usage_attempts"] == 1
    assert usage["failed_usage_tokens"] == 100
    assert usage["failed_usage_tokens"] <= (usage["prompt_tokens"]
                                            + usage["completion_tokens"])
    # Additive: a reader of the old payload's five keys still finds them.
    assert {"calls", "prompt_tokens", "completion_tokens", "seconds",
            "failures"} <= set(usage)
