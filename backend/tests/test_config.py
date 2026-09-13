from app.core.config import get_settings


def test_settings_defaults(settings):
    assert settings.app_name == "AgentABI"
    assert settings.environment == "local"
    assert str(settings.postgres_dsn).startswith("postgresql+asyncpg://")
    assert str(settings.redis_dsn).startswith("redis://")


def test_postgres_dsn_is_overridable_via_env_var(monkeypatch):
    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://someone:secret@db.internal:5432/agentabi_staging",
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        dsn = str(settings.postgres_dsn)
        assert dsn.startswith("postgresql+asyncpg://")
        assert "db.internal" in dsn
        assert "agentabi_staging" in dsn
    finally:
        get_settings.cache_clear()
