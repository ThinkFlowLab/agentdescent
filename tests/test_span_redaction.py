"""Span values are redacted at the boundary, not only on `MemoryOperation` (#1063).

`#947` put `_safe_value` on `MemoryOperation.attributes` / `expected_effect`
and on the span paths its own tests walked. Three entry points still copied a
caller's mapping verbatim -- `set_attribute`, `add_event` and `start_span`'s
`attributes` -- and `to_span_attributes()` re-emitted the immutable memory
fields raw. A span leaves the process, so each of those paths is pinned here,
with the `#947` control rows kept green by `tests/test_memory_spans.py`.
"""

from __future__ import annotations

import pytest

from agentdescent.rsi_telemetry import (
    MemoryOperation,
    RSITelemetry,
    TelemetrySpan,
)

SECRET = "sk-live-abcdef123456"
REDACTED = "[redacted]"


def _telemetry() -> RSITelemetry:
    counter = iter(range(1, 1000))
    return RSITelemetry(clock=lambda: 10.0,
                        id_factory=lambda kind: f"{kind}-{next(counter)}")


def test_memory_operation_span_attributes_redact_the_immutable_fields() -> None:
    operation = MemoryOperation(
        "write", "sk-live-lesson-abcdef123456",
        precondition=SECRET, evidence_hash=SECRET, verifier=SECRET,
        reason=SECRET, attributes={"label": "kept"})

    attributes = operation.to_span_attributes()

    for key in ("memory.lesson_id", "memory.precondition",
                "memory.evidence_hash", "memory.verifier", "memory.reason"):
        assert attributes[key] == REDACTED, key
    assert attributes["label"] == "kept"

    control = MemoryOperation("write", "lesson-1", precondition="base v1",
                              evidence_hash="abc", verifier="v1")
    clean = control.to_span_attributes()
    assert clean["memory.precondition"] == "base v1"
    assert clean["memory.evidence_hash"] == "abc"
    assert clean["memory.verifier"] == "v1"


def test_set_attribute_redacts_the_value() -> None:
    span = _telemetry().start_span("op")

    span.set_attribute("note", SECRET)
    span.set_attribute("count", 3)

    assert span.attributes["note"] == REDACTED
    assert span.attributes["count"] == 3


def test_add_event_redacts_the_value() -> None:
    telemetry = _telemetry()
    span = telemetry.start_span("op")

    event = telemetry.event(span, "adopt", {"detail": SECRET, "artifact_id": "a1"})

    assert event.attributes["detail"] == REDACTED
    assert event.attributes["artifact_id"] == "a1"


def test_start_span_redacts_the_initial_attributes() -> None:
    span = _telemetry().start_span("op", attributes={"detail": SECRET,
                                                     "artifact_id": "a1"})

    assert span.attributes["detail"] == REDACTED
    assert span.attributes["artifact_id"] == "a1"


def test_a_directly_constructed_span_redacts_too() -> None:
    span = TelemetrySpan(trace_id="t", span_id="s", name="op", kind="span",
                         start=1.0, attributes={"detail": SECRET})

    assert span.attributes["detail"] == REDACTED


def test_exception_event_redacts_the_message() -> None:
    telemetry = _telemetry()

    with pytest.raises(RuntimeError):
        with telemetry.span("op") as span:
            raise RuntimeError(f"auth failed with {SECRET}")

    (event,) = span.events
    assert event.name == "exception"
    assert event.attributes["type"] == "RuntimeError"
    assert event.attributes["message"] == REDACTED
    assert SECRET not in str(span.events)
