"""W3C trace-context propagation across Kafka (Phase 15 spec §10 —
mandatory). Trace context travels in Kafka message headers only, never
inside the event payload/`EventEnvelope` — this module is the sole
place that reads/writes those headers, so the header key names live in
exactly one place.

Both functions are pure and degrade to no-ops when OTel isn't
installed/enabled, so they're safe to call unconditionally from the
publisher/consumer without an `if settings.otel_enabled` check at every
call site.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Only for the return annotation below — never imported at runtime
    # (this module stays importable with OTel absent/disabled; see
    # `_otel_available()`), and `from __future__ import annotations`
    # above means this string-deferred annotation never actually
    # evaluates the import either.
    from opentelemetry.context import Context

KafkaHeaders = list[tuple[str, bytes]]


def _otel_available() -> bool:
    try:
        import opentelemetry.propagate  # noqa: F401
    except ImportError:
        return False
    return True


def inject_trace_headers() -> KafkaHeaders:
    """Called from the producer, inside the active FastAPI/webhook span
    (spec §10's "FastAPI span -> inject -> Kafka headers"). Returns an
    empty list when there is no active context or OTel isn't
    available — `aiokafka`'s `headers=` accepts `[]` fine."""

    if not _otel_available():
        return []
    from opentelemetry.propagate import inject

    carrier: dict[str, str] = {}
    inject(carrier)  # writes traceparent/tracestate if a span is active
    return [(key, value.encode("utf-8")) for key, value in carrier.items()]


def extract_trace_context(headers: KafkaHeaders | None) -> Context | None:
    """Called from the consumer before starting its own span (spec
    §10's "Kafka headers -> extract -> worker consumer span"). Returns
    an OTel `Context` (or `None` if unavailable) suitable for
    `context.attach()`/passing to `start_as_current_span(context=...)`."""

    if not _otel_available():
        return None
    if not headers:
        return None

    from opentelemetry.propagate import extract
    from opentelemetry.trace import get_current_span

    carrier: dict[str, str] = {}
    for key, value in headers:
        try:
            carrier[key] = value.decode("utf-8")
        except UnicodeDecodeError:
            # Malformed header (spec §31) — skip it, never raise. A
            # missing/invalid traceparent just means `extract()` starts
            # a fresh trace instead of continuing one.
            continue
    if not carrier:
        return None

    context = extract(carrier)
    span_context = get_current_span(context).get_span_context()
    return context if span_context.is_valid else None


__all__ = ["inject_trace_headers", "extract_trace_context", "KafkaHeaders"]
