async def test_health_ok(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "AgentABI"


async def test_ready_ok_when_database_reachable(client, db_engine):
    response = await client.get("/api/v1/ready")
    body = response.json()
    assert "database" in body["checks"]
    assert body["checks"]["database"] is True
    # Neo4j is not guaranteed to be reachable in every environment this
    # suite runs in (see docs/DECISIONS.md's Neo4j verification section) —
    # this test only asserts the check ran and reported *something*, and
    # that the endpoint's overall status/code agree with the aggregate of
    # whatever every registered check returned.
    assert "graph" in body["checks"]
    all_ok = all(body["checks"].values())
    assert response.status_code == (200 if all_ok else 503)
    assert body["status"] == ("ok" if all_ok else "unavailable")


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
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] is False

    await dispose_engine()
    get_settings.cache_clear()
