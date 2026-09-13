async def test_health_ok(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "AgentABI"


async def test_ready_ok_when_database_reachable(client, db_engine):
    response = await client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] is True


async def test_ready_503_when_database_unreachable(client, monkeypatch):
    from app.core.config import get_settings
    from app.core.database import dispose_engine

    monkeypatch.setenv(
        "POSTGRES_DSN",
        "postgresql+asyncpg://nouser:nopass@localhost:59999/does_not_exist",
    )
    get_settings.cache_clear()
    await dispose_engine()

    response = await client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["database"] is False

    await dispose_engine()
    get_settings.cache_clear()
