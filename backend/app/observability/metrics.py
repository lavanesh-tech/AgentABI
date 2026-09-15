"""Central Prometheus metrics module (Phase 16 spec §5). The only module
that touches `prometheus_client` globals — every other module records
metrics through the small `record_*`/helper functions exported here,
never by importing `prometheus_client` directly. This mirrors Phase 15's
`app.observability.tracing` boundary and its no-op-when-unavailable
posture (spec §24: a metrics failure must never break a request).

Deliberate separation from tracing (spec §33, ADR): OpenTelemetry owns
distributed traces (`app.observability.tracing`); this module owns
Prometheus counters/histograms/gauges directly via `prometheus_client`,
never through OTel's metrics API. Two different concerns, two different
libraries, one clearly-documented boundary each.

Import safety: `prometheus_client` is a pure-Python wheel and expected to
be installable, but this module still degrades to a complete no-op if it
is absent — same defensive pattern as `tracing.py`/`neo4j`/`aiokafka`.
`METRICS_ENABLED=false` skips recording without needing the package
importable at all; the reverse (package missing, flag true) degrades to
the same no-op path rather than raising.

Cardinality safety (spec §22, mandatory): every label attached to any
metric below must come from a small, fixed, code-defined vocabulary —
method names, normalized route templates, HTTP status codes, pipeline
names, PASS/WARN/BLOCK, bounded outcome/category strings. The following
are never used as a label value anywhere in this module or its callers:
project_id, organization_id, component_id, event_id, trace_id,
request_id, correlation_id, pull_request_number, head_sha, email, GitHub
username, raw URLs, or raw exception text. `tests/test_metrics_
cardinality_safety.py` asserts this statically against the label names
declared below.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import structlog

from app.core.config import Settings

logger = structlog.get_logger(__name__)

# spec §22 — label *names* that must never appear anywhere in this file's
# metric declarations. Enforced both by code review and by
# tests/test_metrics_cardinality_safety.py, which greps this module's
# declared labelnames against this exact set.
FORBIDDEN_LABEL_NAMES = frozenset(
    {
        "project_id",
        "organization_id",
        "component_id",
        "event_id",
        "trace_id",
        "request_id",
        "correlation_id",
        "pull_request_number",
        "head_sha",
        "email",
        "github_username",
        "url",
        "exception",
        "exception_message",
    }
)

_registry: Any = None
_worker_server_started = False


def _prometheus_available() -> bool:
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        return False
    return True


class _NoOpMetric:
    """Stand-in with the same call shape as a `prometheus_client` metric
    (`.labels(...).inc()/.observe()/.set()`), used whenever the library
    isn't installed. Callers never branch on availability."""

    def labels(self, *args: Any, **kwargs: Any) -> _NoOpMetric:
        return self

    def inc(self, *args: Any, **kwargs: Any) -> None:
        return None

    def observe(self, *args: Any, **kwargs: Any) -> None:
        return None

    def set(self, *args: Any, **kwargs: Any) -> None:
        return None


_NOOP = _NoOpMetric()


def _get_registry() -> Any:
    global _registry
    if _registry is None and _prometheus_available():
        from prometheus_client import CollectorRegistry

        _registry = CollectorRegistry()
    return _registry


def _assert_safe_labels(labelnames: tuple[str, ...]) -> None:
    unsafe = FORBIDDEN_LABEL_NAMES.intersection(labelnames)
    if unsafe:
        raise ValueError(f"unsafe high-cardinality label(s) declared: {sorted(unsafe)}")


def _counter(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> Any:
    _assert_safe_labels(labelnames)
    if not _prometheus_available():
        return _NOOP
    try:
        from prometheus_client import Counter

        return Counter(name, documentation, labelnames, registry=_get_registry())
    except Exception as exc:  # noqa: BLE001 - never fail import over a metrics registration issue
        logger.warning("metrics_counter_registration_failed", metric=name, error=str(exc))
        return _NOOP


def _histogram(
    name: str,
    documentation: str,
    labelnames: tuple[str, ...] = (),
    *,
    buckets: tuple[float, ...] | None = None,
) -> Any:
    _assert_safe_labels(labelnames)
    if not _prometheus_available():
        return _NOOP
    try:
        from prometheus_client import Histogram

        kwargs: dict[str, Any] = {"registry": _get_registry()}
        if buckets is not None:
            kwargs["buckets"] = buckets
        return Histogram(name, documentation, labelnames, **kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_histogram_registration_failed", metric=name, error=str(exc))
        return _NOOP


def _gauge(name: str, documentation: str, labelnames: tuple[str, ...] = ()) -> Any:
    _assert_safe_labels(labelnames)
    if not _prometheus_available():
        return _NOOP
    try:
        from prometheus_client import Gauge

        return Gauge(name, documentation, labelnames, registry=_get_registry())
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_gauge_registration_failed", metric=name, error=str(exc))
        return _NOOP


# --- HTTP (spec §6) ---------------------------------------------------
HTTP_REQUESTS_TOTAL = _counter(
    "agentabi_http_requests_total",
    "Total HTTP requests handled, by method/normalized route/status.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = _histogram(
    "agentabi_http_request_duration_seconds",
    "HTTP request duration in seconds, by method/normalized route/status.",
    ("method", "route", "status"),
)
HTTP_REQUESTS_IN_PROGRESS = _gauge(
    "agentabi_http_requests_in_progress",
    "HTTP requests currently being handled, by method. Labeled by method "
    "only (not route) since the route template isn't resolved until "
    "after routing runs, partway through the request.",
    ("method",),
)

# --- Analysis pipeline (spec §7) — compatibility/replay/differential/risk
ANALYSIS_RUNS_TOTAL = _counter(
    "agentabi_analysis_runs_total",
    "Total analysis pipeline runs, by pipeline name and outcome.",
    ("pipeline", "status"),
)
ANALYSIS_DURATION_SECONDS = _histogram(
    "agentabi_analysis_duration_seconds",
    "Analysis pipeline run duration in seconds, by pipeline name and outcome.",
    ("pipeline", "status"),
)

# --- Risk decisions (spec §8, mandatory) -------------------------------
RISK_DECISIONS_TOTAL = _counter(
    "agentabi_risk_decisions_total",
    "Total risk decisions recorded, by decision and hard_block flag. "
    "Observed exactly as produced by app.risk.engine — never recalculated here.",
    ("decision", "hard_block"),
)
RISK_SCORE = _histogram(
    "agentabi_risk_score",
    "Distribution of risk scores (0-100) recorded by app.risk.engine.",
    (),
    buckets=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100),
)

# --- Kafka (spec §10) ---------------------------------------------------
KAFKA_PUBLISHED_TOTAL = _counter(
    "agentabi_kafka_published_total",
    "Total Kafka events published, by event type and outcome.",
    ("event_type", "outcome"),
)
KAFKA_PUBLISH_DURATION_SECONDS = _histogram(
    "agentabi_kafka_publish_duration_seconds",
    "Kafka publish call duration in seconds, by event type and outcome.",
    ("event_type", "outcome"),
)
KAFKA_CONSUMED_TOTAL = _counter(
    "agentabi_kafka_consumed_total",
    "Total Kafka events consumed, by event type and outcome.",
    ("event_type", "outcome"),
)
KAFKA_PROCESSING_DURATION_SECONDS = _histogram(
    "agentabi_kafka_processing_duration_seconds",
    "Kafka message processing duration in seconds, by event type and outcome.",
    ("event_type", "outcome"),
)
KAFKA_RETRIES_TOTAL = _counter(
    "agentabi_kafka_retries_total",
    "Total transient-error retries, by event type.",
    ("event_type",),
)
KAFKA_DLQ_TOTAL = _counter(
    "agentabi_kafka_dlq_total",
    "Total messages routed to the dead-letter topic, by event type and reason.",
    ("event_type", "reason"),
)

# --- Worker (spec §14) --------------------------------------------------
WORKER_IN_PROGRESS = _gauge(
    "agentabi_worker_in_progress",
    "Kafka worker messages currently being processed, by event type.",
    ("event_type",),
)

# --- GitHub (spec §16) ---------------------------------------------------
GITHUB_WEBHOOK_DELIVERIES_TOTAL = _counter(
    "agentabi_github_webhook_deliveries_total",
    "Total GitHub webhook deliveries received, by event and outcome.",
    ("event", "outcome"),
)
GITHUB_PR_ANALYSES_TOTAL = _counter(
    "agentabi_github_pr_analyses_total",
    "Total GitHub PR analyses, by outcome (started/completed/failed).",
    ("outcome",),
)
GITHUB_CHECK_PUBLISH_TOTAL = _counter(
    "agentabi_github_check_publish_total",
    "Total GitHub Checks API publish attempts, by action and outcome.",
    ("action", "outcome"),
)
GITHUB_API_FAILURES_TOTAL = _counter(
    "agentabi_github_api_failures_total",
    "Total GitHub API call failures, by action.",
    ("action",),
)

# --- OpenAI (spec §17) ---------------------------------------------------
OPENAI_EXPLANATIONS_TOTAL = _counter(
    "agentabi_openai_explanations_total",
    "Total OpenAI explanation calls, by outcome and model.",
    ("outcome", "model"),
)
OPENAI_EXPLANATION_DURATION_SECONDS = _histogram(
    "agentabi_openai_explanation_duration_seconds",
    "OpenAI explanation call duration in seconds, by outcome and model.",
    ("outcome", "model"),
)

# --- Dependency health (spec §18, optional/broad only) -------------------
DEPENDENCY_REQUESTS_TOTAL = _counter(
    "agentabi_dependency_requests_total",
    "Total outbound dependency calls, by dependency name and outcome. "
    "Broad success/failure signal only — never per-query names or values.",
    ("dependency", "outcome"),
)
DEPENDENCY_REQUEST_DURATION_SECONDS = _histogram(
    "agentabi_dependency_request_duration_seconds",
    "Dependency call duration in seconds, by dependency name and outcome.",
    ("dependency", "outcome"),
)

# --- Errors (spec §20) ---------------------------------------------------
ERRORS_TOTAL = _counter(
    "agentabi_errors_total",
    "Total errors recorded, by bounded category "
    "(validation|dependency|timeout|internal) — never raw exception text.",
    ("error_type",),
)

_VALID_ERROR_TYPES = frozenset({"validation", "dependency", "timeout", "internal"})


# --- Recording helpers ---------------------------------------------------
# Every function below is a thin, always-safe wrapper: it never raises
# (a `.labels()/.inc()/.observe()` failure is caught and logged, spec
# §24), and it never computes or alters a domain decision — callers pass
# in values that were already decided elsewhere (spec §2).


def record_http_request(
    settings: Settings, *, method: str, route: str, status: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=status).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route, status=status).observe(
            duration_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="http_request", error=str(exc))


@contextmanager
def track_http_in_progress(settings: Settings, *, method: str) -> Iterator[None]:
    if not settings.metrics_enabled:
        yield
        return
    try:
        gauge = HTTP_REQUESTS_IN_PROGRESS.labels(method=method)
        gauge.inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="http_in_progress", error=str(exc))
        gauge = None
    try:
        yield
    finally:
        if gauge is not None:
            try:
                gauge.dec()
            except Exception as exc:  # noqa: BLE001
                logger.warning("metrics_record_failed", metric="http_in_progress", error=str(exc))


def record_analysis_run(
    settings: Settings, *, pipeline: str, status: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        ANALYSIS_RUNS_TOTAL.labels(pipeline=pipeline, status=status).inc()
        ANALYSIS_DURATION_SECONDS.labels(pipeline=pipeline, status=status).observe(duration_seconds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="analysis_run", error=str(exc))


def record_risk_decision(
    settings: Settings, *, decision: str, hard_block: bool, score: float
) -> None:
    """Spec §8 mandatory: `decision`/`hard_block`/`score` must be exactly
    what `app.risk.engine.evaluate()` already produced — this function
    only observes them, never derives or recomputes anything."""

    if not settings.metrics_enabled:
        return
    try:
        RISK_DECISIONS_TOTAL.labels(decision=decision, hard_block=str(hard_block).lower()).inc()
        RISK_SCORE.observe(score)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="risk_decision", error=str(exc))


def record_kafka_published(
    settings: Settings, *, event_type: str, outcome: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        KAFKA_PUBLISHED_TOTAL.labels(event_type=event_type, outcome=outcome).inc()
        KAFKA_PUBLISH_DURATION_SECONDS.labels(event_type=event_type, outcome=outcome).observe(
            duration_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="kafka_published", error=str(exc))


def record_kafka_consumed(
    settings: Settings, *, event_type: str, outcome: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        KAFKA_CONSUMED_TOTAL.labels(event_type=event_type, outcome=outcome).inc()
        KAFKA_PROCESSING_DURATION_SECONDS.labels(event_type=event_type, outcome=outcome).observe(
            duration_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="kafka_consumed", error=str(exc))


def record_kafka_retry(settings: Settings, *, event_type: str) -> None:
    if not settings.metrics_enabled:
        return
    try:
        KAFKA_RETRIES_TOTAL.labels(event_type=event_type).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="kafka_retry", error=str(exc))


def record_kafka_dlq(settings: Settings, *, event_type: str, reason: str) -> None:
    if not settings.metrics_enabled:
        return
    try:
        KAFKA_DLQ_TOTAL.labels(event_type=event_type, reason=reason).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="kafka_dlq", error=str(exc))


@contextmanager
def track_worker_in_progress(settings: Settings, *, event_type: str) -> Iterator[None]:
    if not settings.metrics_enabled:
        yield
        return
    try:
        gauge = WORKER_IN_PROGRESS.labels(event_type=event_type)
        gauge.inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="worker_in_progress", error=str(exc))
        gauge = None
    try:
        yield
    finally:
        if gauge is not None:
            try:
                gauge.dec()
            except Exception as exc:  # noqa: BLE001
                logger.warning("metrics_record_failed", metric="worker_in_progress", error=str(exc))


def record_github_webhook_delivery(settings: Settings, *, event: str, outcome: str) -> None:
    if not settings.metrics_enabled:
        return
    try:
        GITHUB_WEBHOOK_DELIVERIES_TOTAL.labels(event=event, outcome=outcome).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="github_webhook_delivery", error=str(exc))


def record_github_pr_analysis(settings: Settings, *, outcome: str) -> None:
    if not settings.metrics_enabled:
        return
    try:
        GITHUB_PR_ANALYSES_TOTAL.labels(outcome=outcome).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="github_pr_analysis", error=str(exc))


def record_github_check_publish(settings: Settings, *, action: str, outcome: str) -> None:
    if not settings.metrics_enabled:
        return
    try:
        GITHUB_CHECK_PUBLISH_TOTAL.labels(action=action, outcome=outcome).inc()
        if outcome == "failure":
            GITHUB_API_FAILURES_TOTAL.labels(action=action).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="github_check_publish", error=str(exc))


def record_openai_explanation(
    settings: Settings, *, outcome: str, model: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        OPENAI_EXPLANATIONS_TOTAL.labels(outcome=outcome, model=model).inc()
        OPENAI_EXPLANATION_DURATION_SECONDS.labels(outcome=outcome, model=model).observe(
            duration_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="openai_explanation", error=str(exc))


def record_dependency_call(
    settings: Settings, *, dependency: str, outcome: str, duration_seconds: float
) -> None:
    if not settings.metrics_enabled:
        return
    try:
        DEPENDENCY_REQUESTS_TOTAL.labels(dependency=dependency, outcome=outcome).inc()
        DEPENDENCY_REQUEST_DURATION_SECONDS.labels(dependency=dependency, outcome=outcome).observe(
            duration_seconds
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="dependency_call", error=str(exc))


def record_error(settings: Settings, *, error_type: str) -> None:
    """`error_type` must be one of `_VALID_ERROR_TYPES` (spec §20) — an
    unrecognized category is coerced to "internal" rather than accepted
    as an arbitrary label value, which is what keeps this metric's
    cardinality bounded regardless of caller mistakes."""

    if not settings.metrics_enabled:
        return
    category = error_type if error_type in _VALID_ERROR_TYPES else "internal"
    try:
        ERRORS_TOTAL.labels(error_type=category).inc()
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_record_failed", metric="error", error=str(exc))


def render_metrics(settings: Settings) -> tuple[bytes, str]:
    """Returns `(body, content_type)` for the `/metrics` endpoint
    (spec §6: Prometheus-scrape-compatible, not JSON-serialized, no
    AgentABI JWT). Degrades to a plain-text placeholder — never a 500 —
    when metrics are disabled or `prometheus_client` isn't installed, so
    a scrape target is never a hard failure either way."""

    if not settings.metrics_enabled or not _prometheus_available():
        return (
            b"# AgentABI metrics disabled or prometheus_client not installed\n",
            "text/plain; charset=utf-8",
        )
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return generate_latest(_get_registry()), CONTENT_TYPE_LATEST
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_render_failed", error=str(exc))
        return b"# metrics render failed\n", "text/plain; charset=utf-8"


def start_worker_metrics_server(settings: Settings) -> None:
    """Spec §14: the Kafka worker must not be forced to run FastAPI just
    to expose `/metrics` — `prometheus_client.start_http_server` opens a
    tiny stdlib-http.server-based listener on its own port instead. A
    no-op if disabled, unavailable, or already started (idempotent, same
    posture as `tracing.setup_tracing`)."""

    global _worker_server_started
    if _worker_server_started or not settings.metrics_enabled or not _prometheus_available():
        return
    try:
        from prometheus_client import start_http_server

        start_http_server(settings.metrics_worker_port, registry=_get_registry())
        _worker_server_started = True
        logger.info("metrics_worker_server_started", port=settings.metrics_worker_port)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics_worker_server_failed", error=str(exc))


def _elapsed_seconds(start: float) -> float:
    return time.monotonic() - start


__all__ = [
    "FORBIDDEN_LABEL_NAMES",
    "record_http_request",
    "track_http_in_progress",
    "record_analysis_run",
    "record_risk_decision",
    "record_kafka_published",
    "record_kafka_consumed",
    "record_kafka_retry",
    "record_kafka_dlq",
    "track_worker_in_progress",
    "record_github_webhook_delivery",
    "record_github_pr_analysis",
    "record_github_check_publish",
    "record_openai_explanation",
    "record_dependency_call",
    "record_error",
    "render_metrics",
    "start_worker_metrics_server",
]
