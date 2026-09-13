"""Async SQLAlchemy engine/session lifecycle + FastAPI session dependency.

Single module owning the engine and session factory as process-wide
singletons (created lazily, disposed explicitly on shutdown) so every
request/worker shares one connection pool instead of each opening its own.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide async engine, creating it on first use.

    `pool_pre_ping` issues a cheap `SELECT 1` before handing out a pooled
    connection so a connection killed by a restart/load balancer/idle
    timeout is detected and replaced rather than surfacing as a mid-request
    `OperationalError`.
    """

    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_async_engine(
            str(settings.postgres_dsn),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=settings.debug and settings.is_local,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, committed on success,
    rolled back on any exception, always closed. Route handlers should
    depend on this rather than importing the session factory directly, so
    tests can override it (`app.dependency_overrides[get_db_session]`).
    """

    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """Readiness probe: can we actually open a connection and query
    Postgres right now? Distinct from `/health`, which only proves the
    process is alive. Never raises — callers get a bool and the exception
    (if any) is logged with context.
    """

    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        logger.exception("database_readiness_check_failed")
        return False


async def dispose_engine() -> None:
    """Close the connection pool. Called from the FastAPI lifespan on
    shutdown so the process doesn't leak open sockets to Postgres."""

    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
