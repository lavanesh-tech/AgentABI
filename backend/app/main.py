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
from app.core.database import dispose_engine
from app.core.logging import configure_logging, get_logger
from app.core.middleware import CorrelationIdMiddleware
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
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Agent Compatibility & Upgrade Intelligence Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    register_exception_handlers(app)

    return app


app = create_app()
