"""Structured logging foundation.

Configures structlog to emit either human-readable console logs (local dev)
or single-line JSON logs (staging/production, consumable by CloudWatch /
Grafana Loki / any log pipeline). Every log line carries a `correlation_id`
when one is bound via `bind_correlation_id`, which request middleware
(added in a later phase) will populate per-request.
"""

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings


def _add_trace_context(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Phase 15 spec §9: enrich logs emitted inside a traced execution
    with `trace_id`/`span_id`, alongside (never replacing)
    `correlation_id`. A no-op outside any span, or when OTel isn't
    installed/enabled — `current_trace_context()` never raises."""

    from app.observability.tracing import current_trace_context

    ctx = current_trace_context()
    if ctx:
        event_dict.update(ctx)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog once, at process startup."""

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level),
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_trace_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation/request ID to all subsequent log calls on this
    context (async-safe via contextvars). Cleared per-request by middleware.
    """

    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)


def clear_contextvars() -> None:
    structlog.contextvars.clear_contextvars()
