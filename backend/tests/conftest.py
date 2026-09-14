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


# Mirrors the immutability triggers created by migrations
# 0002/0003/0004/0005. Base.metadata.create_all() (used only in tests, never
# for the app's real schema — see docs/ARCHITECTURE.md) creates tables
# from the ORM but knows nothing about raw-SQL triggers, so any test that
# needs a database-level immutability backstop needs it created here too.
_IMMUTABILITY_DDL = """
CREATE OR REPLACE FUNCTION prevent_component_version_mutation()
RETURNS trigger AS $$
BEGIN
    IF NEW.content IS DISTINCT FROM OLD.content
       OR NEW.checksum IS DISTINCT FROM OLD.checksum THEN
        RAISE EXCEPTION
            'component_versions.content/checksum are immutable (id=%)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_component_versions_immutable ON component_versions;
CREATE TRIGGER trg_component_versions_immutable
BEFORE UPDATE ON component_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_component_version_mutation();

CREATE OR REPLACE FUNCTION prevent_compatibility_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'compatibility scan evidence is immutable once created (table=%, id=%)',
        TG_TABLE_NAME, OLD.id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_compatibility_scans_immutable ON compatibility_scans;
CREATE TRIGGER trg_compatibility_scans_immutable
BEFORE UPDATE ON compatibility_scans
FOR EACH ROW
EXECUTE FUNCTION prevent_compatibility_evidence_mutation();

DROP TRIGGER IF EXISTS trg_scan_changes_immutable ON scan_changes;
CREATE TRIGGER trg_scan_changes_immutable
BEFORE UPDATE ON scan_changes
FOR EACH ROW
EXECUTE FUNCTION prevent_compatibility_evidence_mutation();

CREATE OR REPLACE FUNCTION prevent_trajectory_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'trajectory_events are immutable once created (id=%)', OLD.id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_trajectory_events_immutable ON trajectory_events;
CREATE TRIGGER trg_trajectory_events_immutable
BEFORE UPDATE ON trajectory_events
FOR EACH ROW
EXECUTE FUNCTION prevent_trajectory_event_mutation();

CREATE OR REPLACE FUNCTION prevent_replay_step_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'replay_steps are immutable once created (id=%)', OLD.id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_replay_steps_immutable ON replay_steps;
CREATE TRIGGER trg_replay_steps_immutable
BEFORE UPDATE ON replay_steps
FOR EACH ROW
EXECUTE FUNCTION prevent_replay_step_mutation();

CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events are immutable and append-only (id=%)',
        COALESCE(OLD.id, NEW.id);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_events_immutable_update ON audit_events;
CREATE TRIGGER trg_audit_events_immutable_update
BEFORE UPDATE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_event_mutation();

DROP TRIGGER IF EXISTS trg_audit_events_immutable_delete ON audit_events;
CREATE TRIGGER trg_audit_events_immutable_delete
BEFORE DELETE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_event_mutation();
"""


@pytest.fixture
async def db_engine(monkeypatch):
    """Points the app at a real Postgres test database (`agentabi_test` by
    default, override with TEST_POSTGRES_DSN) and creates/drops all tables
    (plus the immutability trigger) around the test. Requires a reachable
    Postgres — tests using this fixture are integration tests, not unit
    tests, by design.
    """

    from sqlalchemy import text

    from app.core.database import dispose_engine, get_engine
    from app.models import Base

    monkeypatch.setenv("POSTGRES_DSN", TEST_DATABASE_URL)
    get_settings.cache_clear()
    await dispose_engine()

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_IMMUTABILITY_DDL))

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await dispose_engine()
    get_settings.cache_clear()


@pytest.fixture
async def session(db_engine):
    """A real AsyncSession against the test database, for service-layer
    integration tests that don't need the HTTP layer."""

    from app.core.database import get_session_factory

    async with get_session_factory()() as db_session:
        yield db_session
