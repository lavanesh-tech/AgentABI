"""FastAPI application factory and ASGI entrypoint.

Run locally with: uvicorn app.main:app --reload
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.cors import build_cors_kwargs
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.metrics_middleware import PrometheusMetricsMiddleware
from app.core.middleware import CorrelationIdMiddleware
from app.core.redis import dispose_redis_client
from app.core.request_size import RequestSizeLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.graph.client import dispose_driver
from app.observability import (
    instrument_fastapi_app,
    instrument_httpx,
    render_metrics,
    setup_tracing,
    shutdown_tracing,
)

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)
# Process-wide, idempotent (spec §30) — safe even though `create_app()`
# runs once per test in this codebase's suite. No-op when
# `OTEL_ENABLED=false` (the default) or the SDK isn't installed.
setup_tracing(settings)
instrument_httpx(settings)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", environment=settings.environment)
    yield
    await dispose_engine()
    await dispose_driver()
    await dispose_redis_client()
    if settings.kafka_enabled:
        # Lazy import: a process that never enables Kafka should never
        # need `aiokafka` importable to start up or shut down cleanly
        # (spec §12).
        from app.events.factory import dispose_event_publisher

        await dispose_event_publisher()
    # Flushes/closes the OTel exporter (spec §4/§29). A no-op when
    # tracing was never initialized.
    shutdown_tracing()
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Agent Compatibility & Upgrade Intelligence Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware order (Starlette: the LAST add_middleware call becomes
    # the OUTERMOST layer, so it sees the request first / the response
    # last). RequestSizeLimitMiddleware is added last so oversized
    # requests are rejected before any other middleware or routing does
    # work on them. The others are BaseHTTPMiddleware layers wrapping
    # the same inner Request/response cycle — their relative order
    # doesn't affect correctness here, since request.state (used by
    # CorrelationIdMiddleware/errors.py) is set on the shared ASGI scope
    # before call_next() reaches anything downstream.
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        **build_cors_kwargs(
            allow_origins=settings.cors_allow_origins,
            allow_credentials=settings.cors_allow_credentials,
        ),
    )
    app.add_middleware(RequestSizeLimitMiddleware, settings=settings)
    # Outermost layer (spec §6): added last so its timing covers every
    # other middleware too, not just route handling.
    app.add_middleware(PrometheusMetricsMiddleware, settings=settings)

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    register_exception_handlers(app)

    # spec §7/§30: instruments this specific app instance, guarded
    # against double-instrumentation; no-op when tracing is disabled.
    instrument_fastapi_app(app, settings)

    # Phase 16 spec §6: plain Prometheus-text endpoint, deliberately
    # outside api_router/api_v1_prefix — no JSON envelope, no AgentABI
    # JWT dependency (this is meant for a local/internal-network scraper,
    # not an authenticated API client; see docs/ARCHITECTURE.md's Phase
    # 16 section for the documented security boundary), and excluded
    # from the OpenAPI schema since it isn't a JSON API route.
    @app.get(settings.metrics_path, include_in_schema=False)
    async def metrics_endpoint() -> Response:
        body, content_type = render_metrics(settings)
        return Response(content=body, media_type=content_type)

    return app


app = create_app()
