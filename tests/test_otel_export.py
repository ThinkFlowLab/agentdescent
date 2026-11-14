"""The opt-in OTLP bridge, pinned without a collector (#923).

A real collector smoke test is documented as *not run*: the CI suite is offline
and the `otel` extra is not installed there. Everything below asserts the shape
a host would see -- span names and attributes, then metric names -- through a
fake exporter the bridge accepts as a `TelemetryExporter`.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from agentdescent.otel_export import (
    DecisionSample,
    ExportedMetric,
    ExportedSpan,
    RoundSample,
    export_run,
    exporter_from_env,
)
from agentdescent.rsi_metrics import metrics_from_records, to_prometheus

ROOT = pathlib.Path(__file__).resolve().parent.parent


class FakeExporter:
    """A host's exporter, so the test needs no collector and no network."""

    def __init__(self) -> None:
        self.spans: list = []
        self.metrics: list = []

    def export_span(self, span: ExportedSpan) -> None:
        self.spans.append(span)

    def export_metric(self, metric: ExportedMetric) -> None:
        self.metrics.append(metric)


ROUNDS = (
    RoundSample(1, reward=0.2, committed=1, rejected=2, tokens=90,
                wallclock=1.5, start=10.0, end=11.5),
    RoundSample(2, reward=0.35, committed=2, rejected=1, tokens=120,
                wallclock=2.0, start=11.5, end=13.5),
)

DECISIONS = (
    DecisionSample("skill", True, calls=3, prompt_tokens=300,
                   completion_tokens=60, wallclock=1.2, start=10.1, end=11.3),
    DecisionSample("prompt", False, calls=1, prompt_tokens=40,
                   completion_tokens=8, wallclock=0.2, start=11.6, end=11.8),
)


def _metrics():
    records = [
        {"accepted": d.accepted, "category": d.category,
         "cost": {"calls": d.calls, "prompt_tokens": d.prompt_tokens,
                  "completion_tokens": d.completion_tokens,
                  "wallclock": d.wallclock}}
        for d in DECISIONS
    ]
    return metrics_from_records(records)


def _export(rounds=ROUNDS, decisions=DECISIONS, **kwargs):
    exporter = FakeExporter()
    export_run(exporter, run_id="run-1", metrics=_metrics(),
               rounds=rounds, decisions=decisions, tenant="acme", **kwargs)
    return exporter


def test_a_small_run_exports_one_span_per_round_and_per_decision() -> None:
    exporter = _export()

    assert [span.name for span in exporter.spans] == [
        "agentdescent.round", "agentdescent.round",
        "agentdescent.decision", "agentdescent.decision",
    ]
    first = exporter.spans[0]
    assert first.attributes == {
        "run.id": "run-1", "run.tenant": "acme", "round.number": 1,
        "round.reward": 0.2, "round.committed": 1, "round.rejected": 2,
        "round.tokens": 90, "round.wallclock": 1.5,
    }
    assert (first.start, first.end) == (10.0, 11.5)
    decision = exporter.spans[2]
    assert decision.attributes == {
        "run.id": "run-1", "run.tenant": "acme", "decision.category": "skill",
        "decision.accepted": True, "decision.calls": 3,
        "decision.prompt_tokens": 300, "decision.completion_tokens": 60,
        "decision.wallclock": 1.2,
    }


def test_the_exported_metrics_reuse_the_rsi_metrics_families() -> None:
    exporter = _export()

    by_name = {metric.name: metric for metric in exporter.metrics}
    published = to_prometheus(_metrics())
    for name in set(by_name) - {"agentdescent_rsi_round_reward"}:
        assert name in published, name     # same family names as the text export

    assert by_name["agentdescent_rsi_decisions_total"].value == 2
    assert by_name["agentdescent_rsi_accepted_total"].value == 1
    assert by_name["agentdescent_rsi_rejected_total"].value == 1
    assert by_name["agentdescent_rsi_calls_total"].value == 4
    assert by_name["agentdescent_rsi_prompt_tokens_total"].value == 340
    assert by_name["agentdescent_rsi_completion_tokens_total"].value == 68
    assert by_name["agentdescent_rsi_acceptance_rate"].value == pytest.approx(0.5)
    assert by_name["agentdescent_rsi_cost_per_accepted"].value == pytest.approx(4.0)

    rewards = [metric for metric in exporter.metrics
               if metric.name == "agentdescent_rsi_round_reward"]
    assert [metric.value for metric in rewards] == [0.2, 0.35]
    assert all(metric.kind == "histogram" for metric in rewards)


def test_an_unmeasured_reward_is_not_a_zero() -> None:
    exporter = _export(rounds=(RoundSample(1, wallclock=1.0,
                                           start=1.0, end=2.0),))

    assert "round.reward" not in exporter.spans[0].attributes
    assert not [m for m in exporter.metrics
                if m.name == "agentdescent_rsi_round_reward"]


def test_nothing_prompt_shaped_is_exported_by_default() -> None:
    exporter = _export()

    allowed = {
        "run.id", "run.tenant", "round.number", "round.reward",
        "round.committed", "round.rejected", "round.tokens", "round.wallclock",
        "decision.category", "decision.accepted", "decision.calls",
        "decision.prompt_tokens", "decision.completion_tokens",
        "decision.wallclock",
    }
    for span in exporter.spans:
        assert set(span.attributes) <= allowed, span.name
        for value in span.attributes.values():
            assert not (isinstance(value, str) and " " in value), value


def test_the_exporter_is_off_unless_an_endpoint_is_configured() -> None:
    assert exporter_from_env({}) is None
    assert exporter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": ""}) is None


def test_a_configured_endpoint_asks_for_the_extra() -> None:
    try:
        exporter = exporter_from_env(
            {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    except ImportError as exc:     # the extra is not installed in CI
        assert "agentdescent[otel]" in str(exc)
    else:
        assert exporter is not None


def test_importing_the_bridge_does_not_pull_the_extra() -> None:
    code = ("import sys, agentdescent, agentdescent.otel_export; "
            "assert 'opentelemetry' not in sys.modules; print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
