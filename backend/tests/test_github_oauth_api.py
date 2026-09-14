"""GitHub OAuth login/callback API — integration tests (Security Phase B
spec §17). Written and `py_compile`-clean; needs FastAPI/httpx,
unavailable in this sandbox — same bucket as test_auth_api.py. GitHub
itself is mocked via a dependency override
(`get_github_oauth_service`); no real network call is ever made.
"""

from app.api.deps.github_oauth import get_github_oauth_service
from app.auth.oauth_state import InMemoryOAuthStateStore
from app.core.config import get_settings
from app.main import app
from app.services.github_oauth_service import GitHubOAuthService
from tests.test_github_oauth_service import FakeGitHubOAuthClient


def _override_service(session):
    store = InMemoryOAuthStateStore()
    settings = get_settings()

    async def _get_service():
        return GitHubOAuthService(
            session, settings=settings, state_store=store, github_client=FakeGitHubOAuthClient()
        )

    app.dependency_overrides[get_github_oauth_service] = _get_service
    return store


async def test_login_redirects_to_github(client, session):
    _override_service(session)
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize")
    app.dependency_overrides.pop(get_github_oauth_service, None)


async def test_callback_missing_state_returns_401(client, session):
    _override_service(session)
    response = await client.get("/api/v1/auth/github/callback", params={"code": "abc"})
    assert response.status_code == 401
    app.dependency_overrides.pop(get_github_oauth_service, None)


async def test_callback_invalid_state_returns_401(client, session):
    _override_service(session)
    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": "abc", "state": "unknown"}
    )
    assert response.status_code == 401
    app.dependency_overrides.pop(get_github_oauth_service, None)


async def test_callback_denied_returns_401(client, session):
    store = _override_service(session)
    await store.save("s1", ttl_seconds=60)
    response = await client.get(
        "/api/v1/auth/github/callback",
        params={"state": "s1", "error": "access_denied"},
    )
    assert response.status_code == 401
    app.dependency_overrides.pop(get_github_oauth_service, None)


async def test_callback_success_returns_agentabi_jwt(client, session):
    store = _override_service(session)
    await store.save("s1", ttl_seconds=60)
    response = await client.get(
        "/api/v1/auth/github/callback", params={"code": "abc", "state": "s1"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "access_token",
        "token_type",
        "user_id",
        "email",
        "organization_id",
        "role",
        "requires_onboarding",
    }
    assert "gho_" not in body["access_token"]  # never the GitHub token
    app.dependency_overrides.pop(get_github_oauth_service, None)
