"""Phase 15 — centralized OpenTelemetry tracing. Every other module
imports from here rather than touching `opentelemetry.*` directly, so
initialization, redaction, and the disabled/no-op path all live in one
place (spec §4)."""

from app.observability.propagation import extract_trace_context, inject_trace_headers
from app.observability.redaction import safe_attributes
from app.observability.tracing import (
    current_trace_context,
    get_tracer,
    instrument_fastapi_app,
    instrument_httpx,
    instrument_sqlalchemy,
    set_current_span_attributes,
    setup_tracing,
    shutdown_tracing,
    start_span,
)

__all__ = [
    "setup_tracing",
    "shutdown_tracing",
    "get_tracer",
    "start_span",
    "set_current_span_attributes",
    "current_trace_context",
    "instrument_fastapi_app",
    "instrument_httpx",
    "instrument_sqlalchemy",
    "inject_trace_headers",
    "extract_trace_context",
    "safe_attributes",
]
