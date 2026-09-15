"""Phase 15 — centralized OpenTelemetry tracing. Phase 16 extends this
same package (spec §5) with a separate Prometheus metrics module
(`metrics.py`) rather than a new top-level package — one place other
modules import observability helpers from, whether the concern is a
trace span or a counter/histogram. Every other module imports from here
rather than touching `opentelemetry.*`/`prometheus_client` directly, so
initialization, redaction, and the disabled/no-op path all live in one
place (spec §4)."""

from app.observability.metrics import (
    record_analysis_run,
    record_dependency_call,
    record_error,
    record_github_check_publish,
    record_github_pr_analysis,
    record_github_webhook_delivery,
    record_kafka_consumed,
    record_kafka_dlq,
    record_kafka_published,
    record_kafka_retry,
    record_openai_explanation,
    record_risk_decision,
    render_metrics,
    start_worker_metrics_server,
    track_http_in_progress,
    track_worker_in_progress,
)
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
    "record_analysis_run",
    "record_dependency_call",
    "record_error",
    "record_github_check_publish",
    "record_github_pr_analysis",
    "record_github_webhook_delivery",
    "record_kafka_consumed",
    "record_kafka_dlq",
    "record_kafka_published",
    "record_kafka_retry",
    "record_openai_explanation",
    "record_risk_decision",
    "render_metrics",
    "start_worker_metrics_server",
    "track_http_in_progress",
    "track_worker_in_progress",
]
