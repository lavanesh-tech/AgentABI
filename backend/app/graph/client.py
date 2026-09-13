"""Async Neo4j driver lifecycle management.

Mirrors `app/core/database.py`'s pattern for Postgres: a process-wide
singleton driver created lazily, disposed explicitly on shutdown, with a
readiness probe that never raises. Credentials come from
`app.core.config.Settings` (env vars `NEO4J_URI`/`NEO4J_USER`/
`NEO4J_PASSWORD`), never hardcoded.
"""

from neo4j import AsyncDriver, AsyncGraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_driver: AsyncDriver | None = None


def get_driver(settings: Settings | None = None) -> AsyncDriver:
    """Return the process-wide async Neo4j driver, creating it on first
    use. Constructing a driver does not itself open a connection —
    `check_graph_connection()` is what actually proves reachability."""

    global _driver
    if _driver is None:
        settings = settings or get_settings()
        _driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _driver


async def check_graph_connection() -> bool:
    """Readiness probe: can we actually reach Neo4j right now? Never
    raises — callers get a bool, and any driver exception is logged with
    context. Mirrors `check_database_connection()` in
    `app/core/database.py`."""

    try:
        driver = get_driver()
        await driver.verify_connectivity()
        return True
    except (ServiceUnavailable, Neo4jError, OSError):
        logger.exception("graph_readiness_check_failed")
        return False


async def dispose_driver() -> None:
    """Close the driver's connection pool. Called from the FastAPI
    lifespan on shutdown, alongside `dispose_engine()` for Postgres."""

    global _driver
    if _driver is not None:
        await _driver.close()
    _driver = None
