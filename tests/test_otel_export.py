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

from agentdescent import otel_export
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


def test_constructing_needs_the_extra_and_says_so(monkeypatch) -> None:
    """The install line lands at construction, which is what `docs/metrics.md`
    promises.

    A host that only learns at the first span has already counted records it
    cannot deliver, so this row pins the fail-fast branch rather than accepting
    whichever branch the code happens to take.
    """
    def _missing() -> dict:
        raise ImportError(
            "OTLP export needs the optional extra: pip install 'agentdescent[otel]'")

    monkeypatch.setattr(otel_export, "_load_otel", _missing)
    with pytest.raises(ImportError) as excinfo:
        otel_export.OtlpExporter("http://localhost:4318")
    assert "agentdescent[otel]" in str(excinfo.value)
    with pytest.raises(ImportError):
        exporter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example:4318"})


def test_an_endpoint_with_credentials_is_refused_and_never_echoed() -> None:
    with pytest.raises(ValueError) as excinfo:
        otel_export.OtlpExporter("https://user:s3cret@collector.example:4318")
    message = str(excinfo.value)
    assert "credentials" in message
    assert "s3cret" not in message and "user:" not in message


def test_plain_http_is_allowed_only_for_a_literal_loopback_host() -> None:
    for allowed in ("http://localhost:4318", "http://127.0.0.1:4318",
                    "http://[::1]:4318", "http://127.9.9.9:4318"):
        assert otel_export._endpoint_problem(allowed) is None, allowed
    for refused in ("http://collector.example:4318", "http://10.1.2.3:4318",
                    "http://127.0.0.1.nip.io:4318"):
        assert otel_export._endpoint_problem(refused) is not None, refused


def test_the_one_named_escape_hatch_lets_a_private_collector_through(monkeypatch) -> None:
    assert otel_export._endpoint_problem("http://10.1.2.3:4318") is not None
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    exporter = otel_export.OtlpExporter(
        "http://10.1.2.3:4318", env={"AGENTDESCENT_OTEL_ALLOW_INSECURE": "1"})
    assert exporter.endpoint == "http://10.1.2.3:4318"
    # The hatch is opt-in by name, not by a bare "not 0".
    assert otel_export._endpoint_problem(
        "http://10.1.2.3:4318", {"AGENTDESCENT_OTEL_ALLOW_INSECURE": "yes"}) is not None


def test_exporter_from_env_applies_the_same_endpoint_rules(monkeypatch) -> None:
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    with pytest.raises(ValueError):
        exporter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example:4318"})
    with pytest.raises(ValueError):
        exporter_from_env({"OTEL_EXPORTER_OTLP_ENDPOINT": "https://u:p@collector.example:4318"})
    assert exporter_from_env({
        "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector.example:4318"}) is not None
    assert exporter_from_env({
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"}) is not None


def test_importing_the_bridge_does_not_pull_the_extra() -> None:
    code = ("import sys, agentdescent, agentdescent.otel_export; "
            "assert 'opentelemetry' not in sys.modules; print('ok')")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# --- the SDK seam -----------------------------------------------------------
#
# The provider wiring is the part that has to be right per instance, and the
# `[otel]` extra is not installed in CI, so these rows stand in for the SDK at
# `otel_export._load_otel` and inspect what the bridge does with it. They say
# nothing about the SDK's own behaviour, which no offline test can claim -- see
# `Not run:` in the PR body.


class _FakeSpan:
    def __init__(self, name, start_time, attributes) -> None:
        self.name = name
        self.start_time = start_time
        self.attributes = dict(attributes)
        self.status = None
        self.end_time = None

    def set_status(self, status) -> None:
        self.status = status

    def end(self, end_time=None) -> None:
        self.end_time = end_time


class _FakeTracer:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.spans = []

    def start_span(self, name, start_time=None, attributes=None):
        span = _FakeSpan(name, start_time, attributes or {})
        self.spans.append(span)
        return span


class _FakeInstrument:
    def __init__(self) -> None:
        self.added = []
        self.set_values = []

    def add(self, value, attributes) -> None:
        self.added.append((value, dict(attributes)))

    def set(self, value, attributes) -> None:
        self.set_values.append((value, dict(attributes)))


class _FakeMeter:
    def __init__(self, provider) -> None:
        self.provider = provider
        self.instruments = {}

    def _instrument(self, name):
        return self.instruments.setdefault(name, _FakeInstrument())

    def create_counter(self, name, unit=None):
        return self._instrument(name)

    def create_gauge(self, name, unit=None):
        return self._instrument(name)

    def create_histogram(self, name, unit=None):
        return self._instrument(name)


class _FakeSignalExporter:
    """One per signal, so a test can see which endpoint it was built for."""

    def __init__(self, endpoint=None, headers=None) -> None:
        self.endpoint = endpoint
        self.headers = headers


class _FakeProcessor:
    def __init__(self, exporter) -> None:
        self.exporter = exporter


class _FakeReader:
    def __init__(self, exporter) -> None:
        self.exporter = exporter


class _FakeTracerProvider:
    def __init__(self, resource=None) -> None:
        self.resource = resource
        self.processors = []
        self.tracer = None
        self.flushed = []
        self.stopped = False

    def add_span_processor(self, processor) -> None:
        self.processors.append(processor)

    def get_tracer(self, name):
        self.tracer = _FakeTracer(self)
        return self.tracer

    def force_flush(self, timeout_millis=3000):
        self.flushed.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.stopped = True


class _FakeMeterProvider:
    def __init__(self, resource=None, metric_readers=()) -> None:
        self.resource = resource
        self.readers = list(metric_readers)
        self.meter = None
        self.flushed = []
        self.stopped = False

    def get_meter(self, name):
        self.meter = _FakeMeter(self)
        return self.meter

    def force_flush(self, timeout_millis=3000):
        self.flushed.append(timeout_millis)
        return True

    def shutdown(self) -> None:
        self.stopped = True


class _FakeResource:
    @staticmethod
    def create(attributes):
        return dict(attributes)


def _fake_otel():
    return {
        "TracerProvider": _FakeTracerProvider,
        "MeterProvider": _FakeMeterProvider,
        "Resource": _FakeResource,
        "BatchSpanProcessor": _FakeProcessor,
        "PeriodicExportingMetricReader": _FakeReader,
        "OTLPSpanExporter": _FakeSignalExporter,
        "OTLPMetricExporter": _FakeSignalExporter,
        "Status": lambda code, description=None: (code, description),
        "StatusCode": type("StatusCode", (), {"ERROR": "ERROR"}),
    }


def test_two_exporters_do_not_share_a_provider(monkeypatch) -> None:
    """A second exporter must not export through the first one's endpoint.

    The SDK keeps the first provider installed process-wide, so a bridge that
    installed a global provider and then asked the global for a tracer sends
    tenant B's identifiers to tenant A's collector. Each instance owns its
    providers, so a span written through one reaches only that one's tracer.
    """
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    first = otel_export.OtlpExporter("https://a.example:4318",
                                     headers={"x-tenant": "a"})
    second = otel_export.OtlpExporter("https://b.example:4318",
                                      headers={"x-tenant": "b"})

    first.export_span(ExportedSpan("agentdescent.round", {"run.id": "a"},
                                   1.0, 2.0))
    second.export_span(ExportedSpan("agentdescent.round", {"run.id": "b"},
                                    1.0, 2.0))

    assert first._tracer_provider is not second._tracer_provider
    assert first._meter_provider is not second._meter_provider
    assert first._tracer.provider is first._tracer_provider
    assert second._tracer.provider is second._tracer_provider

    assert first._tracer_provider.processors[0].exporter.endpoint == (
        "https://a.example:4318/v1/traces")
    assert second._tracer_provider.processors[0].exporter.endpoint == (
        "https://b.example:4318/v1/traces")
    assert first._meter_provider.readers[0].exporter.endpoint == (
        "https://a.example:4318/v1/metrics")
    assert second._meter_provider.readers[0].exporter.endpoint == (
        "https://b.example:4318/v1/metrics")
    assert second._tracer_provider.processors[0].exporter.headers == {
        "x-tenant": "b"}

    assert [span.attributes["run.id"] for span in first._tracer.spans] == ["a"]
    assert [span.attributes["run.id"] for span in second._tracer.spans] == ["b"]


def test_force_flush_and_shutdown_close_only_this_exporter(monkeypatch) -> None:
    """A short process loses the batch queue unless it flushes; one exporter
    shutting down must not close another host's providers."""
    monkeypatch.setattr(otel_export, "_load_otel", _fake_otel)
    first = otel_export.OtlpExporter("https://a.example:4318")
    second = otel_export.OtlpExporter("https://b.example:4318")
    span = ExportedSpan("agentdescent.round", {"run.id": "run-1"}, 1.0, 2.0)
    first.export_span(span)
    second.export_span(span)

    assert first.force_flush(2500) is True
    assert first._tracer_provider.flushed == [2500]
    assert first._meter_provider.flushed == [2500]
    assert second._tracer_provider.flushed == []

    first.shutdown()
    assert first._tracer_provider.stopped is True
    assert first._meter_provider.stopped is True
    assert second._tracer_provider.stopped is False
    assert second._meter_provider.stopped is False
