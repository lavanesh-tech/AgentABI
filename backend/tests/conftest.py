import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_POSTGRES_DSN",
    "postgresql+asyncpg://agentabi:agentabi@localhost:5432/agentabi_test",
)


@pytest.fixture
def settings():
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
async def client():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_engine(monkeypatch):
    """Points the app at a real Postgres test database (`agentabi_test` by
    default, override with TEST_POSTGRES_DSN) and creates/drops all tables
    around the test. Requires a reachable Postgres — tests using this
    fixture are integration tests, not unit tests, by design.
    """

    from app.core.database import dispose_engine, get_engine
    from app.models import Base

    monkeypatch.setenv("POSTGRES_DSN", TEST_DATABASE_URL)
    get_settings.cache_clear()
    await dispose_engine()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()
    get_settings.cache_clear()
