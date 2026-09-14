"""FastAPI application factory and ASGI entrypoint.

Run locally with: uvicorn app.main:app --reload
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.cors import build_cors_kwargs
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.middleware import CorrelationIdMiddleware
from app.core.redis import dispose_redis_client
from app.core.request_size import RequestSizeLimitMiddleware
from app.core.security_headers import SecurityHeadersMiddleware
from app.graph.client import dispose_driver

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("startup", environment=settings.environment)
    yield
    await dispose_engine()
    await dispose_driver()
    await dispose_redis_client()
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

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    register_exception_handlers(app)

    return app


app = create_app()
