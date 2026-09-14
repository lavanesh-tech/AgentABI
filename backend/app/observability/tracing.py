"""Central OpenTelemetry bootstrap (Phase 15 spec §4). The only module
that touches `opentelemetry.sdk` globals — every other module imports
`get_tracer`/`start_span`/`record_exception` from `app.observability`
rather than calling the SDK directly.

Import safety: `opentelemetry-*` are pure-Python wheels and expected to
be installable, but this module still degrades to a complete no-op if
they are absent (same defensive pattern this codebase already uses for
`neo4j`/`aiokafka` — see docs/DECISIONS.md). `OTEL_ENABLED=false` (the
default) never imports the SDK at all, so a missing package is never
even a code path when telemetry is off — spec §5/§24's "must run
normally when telemetry is disabled" / "export failure must never
break anything" hold structurally, not just by exception handling.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import structlog

from app.core.config import Settings
from app.observability.redaction import safe_attributes

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.trace import Span, Tracer

logger = structlog.get_logger(__name__)

_initialized = False
_instrumented_apps: set[int] = set()


def _otel_available() -> bool:
    try:
        import opentelemetry.sdk.trace  # noqa: F401
    except ImportError:
        return False
    return True


def setup_tracing(settings: Settings) -> None:
    """Idempotent process-wide tracer-provider setup (spec §30). A
    no-op when `OTEL_ENABLED=false` or the SDK isn't installed — in
    both cases `get_tracer()` below still works, returning OTel's own
    no-op tracer, so callers never need to check "is tracing on"."""

    global _initialized
    if _initialized or not settings.otel_enabled:
        return

    if not _otel_available():
        logger.warning("otel_sdk_unavailable", detail="opentelemetry packages not installed")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ALWAYS_OFF,
            ALWAYS_ON,
            ParentBased,
            TraceIdRatioBased,
        )

        resource = Resource.create(
            {
                SERVICE_NAME: settings.otel_service_name,
                SERVICE_VERSION: settings.otel_service_version,
                "deployment.environment": settings.otel_resource_environment,
            }
        )

        if settings.otel_traces_sampler == "always_on":
            sampler = ALWAYS_ON
        elif settings.otel_traces_sampler == "always_off":
            sampler = ALWAYS_OFF
        else:
            # spec §23: parent-based ratio sampling for production;
            # `otel_traces_sampler_arg` (default 1.0) is the local-dev
            # "trace everything" knob — production deployments set a
            # lower ratio via env, never hardcoded here.
            sampler = ParentBased(TraceIdRatioBased(settings.otel_traces_sampler_arg))

        provider = TracerProvider(resource=resource, sampler=sampler)
        exporter = OTLPSpanExporter(endpoint=f"{settings.otel_exporter_otlp_endpoint}/v1/traces")
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _initialized = True
        logger.info(
            "otel_tracing_initialized",
            service_name=settings.otel_service_name,
            endpoint=settings.otel_exporter_otlp_endpoint,
            sampler=settings.otel_traces_sampler,
        )
    except Exception as exc:  # noqa: BLE001 — spec §24: never fail startup over telemetry.
        logger.warning("otel_tracing_setup_failed", error=str(exc))


def shutdown_tracing() -> None:
    """Flushes/closes the exporter (spec §29's worker shutdown, §4's
    "graceful shutdown"). Safe to call even if never initialized."""

    if not _initialized or not _otel_available():
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        shutdown = getattr(provider, "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel_tracing_shutdown_failed", error=str(exc))


def get_tracer(name: str) -> Tracer | None:
    """Returns an OTel tracer if the SDK is importable, else None.
    Callers use `start_span` below rather than this directly in most
    cases; `get_tracer` is exposed for the few call sites that need a
    raw tracer (e.g. FastAPI instrumentation)."""

    if not _otel_available():
        return None
    from opentelemetry import trace

    return trace.get_tracer(name)


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    kind: str | None = None,
    parent_context: Any = None,
) -> Iterator[Span | None]:
    """The one span-creation helper every domain module should use
    (spec §14). Degrades to a no-op contextmanager yielding `None` when
    OTel isn't installed/enabled — callers never branch on this.
    Attributes are always redacted (app.observability.redaction) before
    being attached. Exceptions are recorded on the span and always
    re-raised — tracing never swallows a domain error (spec §22).
    `parent_context` is set by the Kafka consumer (spec §10) after
    extracting W3C headers, so the consumer span is a child of the
    producer's span rather than starting a new trace."""

    if not _otel_available():
        yield None
        return

    from opentelemetry import trace
    from opentelemetry.trace import SpanKind, Status, StatusCode

    tracer = trace.get_tracer("agentabi")
    span_kind = _SPAN_KINDS.get(kind or "internal", SpanKind.INTERNAL)
    with tracer.start_as_current_span(name, context=parent_context, kind=span_kind) as span:
        if attributes:
            for key, value in safe_attributes(attributes).items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))
            raise


def set_current_span_attributes(attributes: dict[str, Any]) -> None:
    """Adds attributes to whatever span is currently active — used where
    a value (event_id, retry_count, outcome) is only known partway
    through a span's lifetime rather than at `start_span()` call time.
    A no-op with no active span or when OTel is unavailable."""

    if not _otel_available():
        return
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        for key, value in safe_attributes(attributes).items():
            span.set_attribute(key, value)
    except Exception:  # noqa: BLE001
        pass


def current_trace_context() -> dict[str, str]:
    """Returns `{"trace_id": ..., "span_id": ...}` for the active span,
    or `{}` outside any span / when OTel is unavailable — used by the
    logging processor (spec §9) and never raises."""

    if not _otel_available():
        return {}
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if not ctx or not ctx.is_valid:
            return {}
        return {"trace_id": format(ctx.trace_id, "032x"), "span_id": format(ctx.span_id, "016x")}
    except Exception:  # noqa: BLE001
        return {}


def instrument_fastapi_app(app: FastAPI, settings: Settings) -> None:
    """Instruments one FastAPI app instance (spec §7). Guarded against
    double-instrumentation (spec §30) since `create_app()` is called
    once per test in this codebase's test suite."""

    if not settings.otel_enabled or not _otel_available():
        return
    if id(app) in _instrumented_apps:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _instrumented_apps.add(id(app))
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel_fastapi_instrumentation_failed", error=str(exc))


def instrument_httpx(settings: Settings) -> None:
    """Global httpx client patch (spec §19) — covers the GitHub checks
    client, GitHub OAuth client, and OpenAI's httpx-backed SDK without
    per-call-site changes. Never records Authorization headers or
    bodies (default instrumentor behavior; nothing here overrides that
    to opt in to body capture)."""

    if not settings.otel_enabled or not _otel_available():
        return
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel_httpx_instrumentation_failed", error=str(exc))


def instrument_sqlalchemy(engine: Any, settings: Settings) -> None:
    """spec §16 — bind parameter values are never captured by this
    instrumentor by default; nothing here changes that."""

    if not settings.otel_enabled or not _otel_available():
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine if hasattr(engine, "sync_engine") else engine
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel_sqlalchemy_instrumentation_failed", error=str(exc))


_SPAN_KINDS: dict[str, Any] = {}


def _load_span_kinds() -> None:
    if not _otel_available():
        return
    from opentelemetry.trace import SpanKind

    _SPAN_KINDS.update(
        {
            "internal": SpanKind.INTERNAL,
            "producer": SpanKind.PRODUCER,
            "consumer": SpanKind.CONSUMER,
            "client": SpanKind.CLIENT,
            "server": SpanKind.SERVER,
        }
    )


_load_span_kinds()


__all__ = [
    "setup_tracing",
    "shutdown_tracing",
    "get_tracer",
    "start_span",
    "current_trace_context",
    "instrument_fastapi_app",
    "instrument_httpx",
    "instrument_sqlalchemy",
]
