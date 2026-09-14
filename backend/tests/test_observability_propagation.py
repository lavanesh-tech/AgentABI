"""Phase 15 spec §31 trace-propagation tests for `app.observability.
propagation` — pure, no collector/broker required. Written and
`py_compile`-clean; not pytest-executed this session (no project
dependency, including `pytest` itself, is installed — see
docs/DECISIONS.md and every prior phase's identical sandbox note).
Once `opentelemetry-api`/`-sdk` are installed, these exercise the real
injector/extractor; today (and whenever OTel isn't installed or
disabled) both functions take their documented no-op path, which is
exactly what `test_disabled_telemetry_returns_noop_values` asserts.
"""

from app.observability.propagation import extract_trace_context, inject_trace_headers


def test_inject_returns_empty_list_with_no_active_span_or_missing_sdk():
    # No OTel SDK installed in this sandbox -> `_otel_available()` is
    # False -> documented no-op: [] (never raises, never fabricates a
    # traceparent).
    headers = inject_trace_headers()
    assert headers == []
    assert isinstance(headers, list)


def test_extract_handles_missing_headers():
    assert extract_trace_context(None) is None


def test_extract_handles_empty_headers():
    assert extract_trace_context([]) is None


def test_extract_handles_malformed_header_bytes_without_raising():
    # Not valid UTF-8 / not a real traceparent — extraction must never
    # raise, only fail to produce a context (spec §31's "malformed/
    # missing tracing headers" case).
    malformed = [("traceparent", b"\xff\xfe not utf8 or valid")]
    try:
        result = extract_trace_context(malformed)
    except UnicodeDecodeError:
        raise AssertionError("extract_trace_context must not raise on malformed headers") from None
    assert result is None  # no-op path in this sandbox (OTel unavailable)


def test_disabled_telemetry_returns_noop_values():
    # Documents the spec §5/§24 invariant this whole module rests on:
    # when OTel isn't available/enabled, both propagation functions are
    # true no-ops — callers (kafka_publisher.py/consumer.py) never
    # branch on "is tracing on" themselves.
    assert inject_trace_headers() == []
    assert extract_trace_context([("traceparent", b"anything")]) is None
