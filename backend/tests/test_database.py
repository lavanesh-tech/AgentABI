"""Database engine/session/readiness behavior.

Tests marked with the `db_engine` fixture are integration tests against a
real Postgres (see conftest.py) — they require Postgres reachable at
TEST_POSTGRES_DSN (default: agentabi_test on localhost).
"""

import pytest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import (
    check_database_connection,
    dispose_engine,
    get_db_session,
    get_engine,
    get_session_factory,
)


def test_get_engine_is_a_singleton(settings):
    engine_a = get_engine()
    engine_b = get_engine()
    assert engine_a is engine_b


def test_get_session_factory_is_bound_to_engine(settings):
    factory = get_session_factory()
    assert factory.kw["bind"] is get_engine()


async def test_check_database_connection_true_when_reachable(db_engine):
    assert await check_database_connection() is True


async def test_check_database_connection_false_when_unreachable(monkeypatch):
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://nouser:nopass@localhost:59999/does_not_exist",
    )
    get_settings.cache_clear()
    await dispose_engine()

    assert await check_database_connection() is False

    await dispose_engine()
    get_settings.cache_clear()


async def test_get_db_session_commits_on_success(db_engine):
    session_gen = get_db_session()
    session = await anext(session_gen)
    await session.execute(text("SELECT 1"))
    # Drive the generator to completion so it hits the commit path.
    with pytest.raises(StopAsyncIteration):
        await anext(session_gen)


async def test_get_db_session_rolls_back_on_exception(db_engine):
    session_gen = get_db_session()
    session = await anext(session_gen)
    assert session is not None

    with pytest.raises(ValueError):
        await session_gen.athrow(ValueError("boom"))
