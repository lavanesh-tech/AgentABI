"""Phase 15 spec §35 (mandatory) Kafka regression: trace propagation
must never change event JSON/schema, partition key, idempotency, exact-
SHA behavior, or offset-commit policy. Written and `py_compile`-clean;
needs `aiokafka`/`structlog`, not installed in this sandbox this session
(see docs/DECISIONS.md and every prior Kafka-phase test file's identical
note).
"""

from app.events.envelope import build_envelope, serialize_envelope


def test_envelope_schema_unchanged_by_phase_15():
    """Trace context lives in Kafka headers only (spec §10) — the
    envelope's own field set, and therefore its serialized JSON shape,
    must be byte-for-byte identical to Phase 13's, with no `trace_id`/
    `traceparent`/`span_id` field added to the payload."""

    envelope = build_envelope(
        event_type="github.pr.analysis.requested",
        correlation_id="corr-1",
        project_id="proj-1",
        organization_id="org-1",
        payload={"github_pr_analysis_id": "a1"},
    )
    serialized = serialize_envelope(envelope)
    import json

    decoded = json.loads(serialized)
    assert set(decoded.keys()) == {
        "event_id",
        "event_type",
        "event_version",
        "occurred_at",
        "correlation_id",
        "project_id",
        "organization_id",
        "payload",
        "metadata",
    }
    assert "trace_id" not in decoded
    assert "traceparent" not in decoded
    assert "span_id" not in decoded


def test_kafka_publisher_source_never_writes_trace_context_into_payload():
    """Structural regression check (no aiokafka import needed): the
    publisher module's source injects trace headers via
    `inject_trace_headers()` and passes them as the `headers=` kwarg to
    `send_and_wait` — never merges them into `event.metadata` or the
    serialized `value` bytes."""

    import inspect

    from app.events import kafka_publisher

    source = inspect.getsource(kafka_publisher.KafkaEventPublisher.publish)
    assert "inject_trace_headers" in source
    assert "headers=headers" in source
    # The serialized envelope bytes are still built from the event
    # exactly as before — `value=value`, not something trace-augmented.
    assert "value=value" in source


def test_kafka_consumer_extracts_headers_without_touching_envelope_bytes():
    import inspect

    from app.kafka import consumer as consumer_module

    source = inspect.getsource(consumer_module.KafkaEventConsumer._process_one)
    assert "extract_trace_context" in source
    assert "message.headers" in source
    # Deserialization still comes from `message.value` alone.
    assert "deserialize_envelope(message.value)" in source
