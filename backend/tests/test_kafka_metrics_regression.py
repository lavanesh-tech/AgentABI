"""Phase 16 spec §39 (mandatory) Kafka regression: metrics recording must
never change the envelope/schema, trace headers, partition key,
idempotency, retry policy, DLQ routing, or offset-commit policy
established in Phases 13/15. Structural source-inspection checks only
(same style as test_kafka_trace_regression.py) — needs `aiokafka`, not
installed in this sandbox this session (PyPI unreachable — see
docs/DECISIONS.md). Written and `py_compile`-clean; not pytest-executed.
"""

import inspect

from app.events import kafka_publisher
from app.kafka import consumer as consumer_module


def test_publisher_still_sends_headers_and_value_unchanged_by_metrics():
    source = inspect.getsource(kafka_publisher.KafkaEventPublisher.publish)
    # Phase 15 invariants, still intact.
    assert "inject_trace_headers" in source
    assert "headers=headers" in source
    assert "value=value" in source
    # Phase 16 addition, alongside — not instead of.
    assert "record_kafka_published" in source


def test_consumer_commit_policy_unchanged_by_metrics_recording():
    dispatch_source = inspect.getsource(consumer_module.KafkaEventConsumer._dispatch_with_retry)
    # Success path still commits before the loop returns.
    assert "await self._consumer.commit()" in dispatch_source
    # The exhausted-retries branch still commits when routing to DLQ.
    assert "transient_retries_exhausted" in dispatch_source
    # The un-exhausted retry branch's own explanatory comment (spec §20's
    # "no commit on a bare transient retry — redelivery is safe because
    # handlers are idempotent") is unchanged, and metrics are recorded
    # right alongside it rather than replacing any of that logic.
    assert "# No commit" in dispatch_source
    assert "record_kafka_retry" in dispatch_source
    retry_call_index = dispatch_source.index("record_kafka_retry")
    no_commit_comment_index = dispatch_source.index("# No commit")
    # The retry metric call must appear before the "no commit" comment,
    # i.e. on the un-exhausted branch, not after some later commit call.
    assert retry_call_index < no_commit_comment_index


def test_dlq_and_consumed_metrics_recorded_without_touching_dlq_payload_shape():
    to_dlq_source = inspect.getsource(consumer_module.KafkaEventConsumer._to_dlq)
    assert "record_kafka_dlq" in to_dlq_source
    # The DLQ publish call itself (message bytes + category + retry
    # count) is unchanged — still the same three positional arguments.
    assert "self._dlq_publish(message.value, failure_category, retry_count)" in to_dlq_source


def test_max_transient_retries_constant_unchanged():
    """Metrics must not alter retry-exhaustion behavior (spec §39) — the
    bounded-retry constant from Phase 13 is untouched."""

    assert consumer_module._MAX_TRANSIENT_RETRIES == 3
