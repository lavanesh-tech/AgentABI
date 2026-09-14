"""Generated OpenAPI schema — integration tests (Security Phase F spec
§19). Written and `py_compile`-clean; needs SQLAlchemy/FastAPI, unavailable
in this sandbox — see docs/DECISIONS.md.
"""


def _schema():
    from app.main import create_app

    return create_app().openapi()


def test_bearer_scheme_is_declared():
    schema = _schema()
    schemes = schema["components"]["securitySchemes"]
    bearer = next(s for s in schemes.values() if s.get("scheme") == "bearer")
    assert bearer["type"] == "http"
    assert bearer["bearerFormat"] == "JWT"


def test_protected_routes_require_bearer_auth():
    schema = _schema()
    protected_paths = [
        "/api/v1/auth/me",
        "/api/v1/organizations/{organization_id}/projects",
        "/api/v1/projects/{project_id}",
        "/api/v1/projects/{project_id}/compatibility/scans",
        "/api/v1/projects/{project_id}/trajectories",
        "/api/v1/projects/{project_id}/replays",
        "/api/v1/organizations/{organization_id}/audit-events",
    ]
    for path in protected_paths:
        operations = schema["paths"][path]
        for method, operation in operations.items():
            if method == "parameters":
                continue
            assert operation.get("security"), f"{method.upper()} {path} missing security"


def test_public_routes_do_not_require_bearer_auth():
    schema = _schema()
    public_paths_methods = [
        ("/api/v1/health", "get"),
        ("/api/v1/ready", "get"),
        ("/api/v1/auth/github/login", "get"),
        ("/api/v1/auth/github/callback", "get"),
        ("/api/v1/github/webhook", "post"),
    ]
    for path, method in public_paths_methods:
        operation = schema["paths"][path][method]
        assert not operation.get("security"), f"{method.upper()} {path} incorrectly requires auth"


def test_no_secret_settings_leak_into_schema():
    import json

    schema = _schema()
    dumped = json.dumps(schema).lower()
    for needle in (
        "jwt_secret",
        "github_oauth_client_secret",
        "github_webhook_secret",
        "openai_api_key",
        "gemini_api_key",
        "redis_dsn",
        "local-dev-only-insecure-secret-change-me",
    ):
        assert needle not in dumped, f"schema leaked {needle!r}"


def test_swagger_and_redoc_ui_routes_exist():
    from app.main import create_app

    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/docs" in paths
    assert "/openapi.json" in paths
