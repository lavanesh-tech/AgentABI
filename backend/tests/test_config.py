def test_settings_defaults(settings):
    assert settings.app_name == "AgentABI"
    assert settings.environment == "local"
    assert str(settings.postgres_dsn).startswith("postgresql+asyncpg://")
    assert str(settings.redis_dsn).startswith("redis://")
