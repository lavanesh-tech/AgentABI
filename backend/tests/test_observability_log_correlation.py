"""Phase 15 spec §32 log-correlation tests for `app.core.logging`'s
`_add_trace_context` processor. Pure function, but imports
`app.core.logging` which imports `structlog` — not installed in this
sandbox this session (see docs/DECISIONS.md). Written and
`py_compile`-clean; not pytest-executed.
"""

from app.core.logging import _add_trace_context


def test_no_active_span_leaves_event_dict_unchanged():
    # OTel unavailable/disabled in this sandbox -> current_trace_context()
    # returns {} -> the processor must not add invalid/empty trace_id or
    # span_id fields (spec §32's "no invalid IDs emitted outside a span").
    event_dict = {"event": "test", "correlation_id": "abc-123"}
    result = _add_trace_context(None, "info", dict(event_dict))
    assert result == event_dict
    assert "trace_id" not in result
    assert "span_id" not in result


def test_correlation_id_is_untouched_by_trace_context_processor():
    # spec §8: request_id/correlation_id are never replaced by trace IDs.
    event_dict = {"correlation_id": "keep-me"}
    result = _add_trace_context(None, "info", dict(event_dict))
    assert result["correlation_id"] == "keep-me"
