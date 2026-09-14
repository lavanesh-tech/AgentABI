"""Security response headers — integration tests (Security Phase D
spec §12/§13/§25). Written and `py_compile`-clean; needs SQLAlchemy/
FastAPI/httpx, unavailable in this sandbox — see docs/DECISIONS.md.
"""


async def test_normal_response_has_baseline_security_headers(client):
    response = await client.get("/api/v1/health")
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert response.headers.get("referrer-policy") == "no-referrer"
    assert response.headers.get("x-frame-options") == "DENY"


async def test_no_content_security_policy_header_present(client):
    # Deliberately not set at the API layer (would break Swagger UI) —
    # see docs/ARCHITECTURE.md.
    response = await client.get("/api/v1/health")
    assert "content-security-policy" not in {k.lower() for k in response.headers}


async def test_hsts_not_sent_in_local_environment(client):
    response = await client.get("/api/v1/health")
    assert "strict-transport-security" not in {k.lower() for k in response.headers}


async def test_auth_response_is_not_cached_by_intermediaries(client):
    response = await client.get("/api/v1/auth/me")
    assert response.headers.get("cache-control") == "no-store"


async def test_swagger_docs_remains_functional():
    from app.main import create_app

    app = create_app()
    route_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/docs" in route_paths
    assert "/openapi.json" in route_paths
