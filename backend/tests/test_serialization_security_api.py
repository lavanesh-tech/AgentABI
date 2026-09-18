"""Response serialization security — integration tests (Security Phase D
spec §15/§16/§27). Written and `py_compile`-clean; needs SQLAlchemy/
FastAPI/httpx, unavailable in this sandbox — see docs/DECISIONS.md. Uses
fake/placeholder values only — never real credentials.

Asserts that representative authenticated responses never contain any
of the secret-shaped strings a raw ORM object or misconfigured response
model could leak.
"""

import uuid

from app.auth.jwt import encode_token
from app.core.config import get_settings

_FORBIDDEN_SUBSTRINGS = (
    "github_access_token",
    "github_client_secret",
    "jwt_secret",
    "webhook_secret",
    "openai_api_key",
    "gemini_api_key",
    "local-dev-only-insecure-secret-change-me",
)


def _assert_no_secrets_leaked(response_text: str) -> None:
    lowered = response_text.lower()
    for needle in _FORBIDDEN_SUBSTRINGS:
        assert needle not in lowered, f"response leaked {needle!r}"


async def test_auth_me_response_never_contains_secret_fields(client, session):
    from app.models import Organization, OrganizationMember, OrganizationRole, User

    settings = get_settings()
    user = User(email="fake@example.com", full_name="Fake User", is_active=True)
    session.add(user)
    await session.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    session.add(
        OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.ADMIN)
    )
    await session.flush()
    await session.commit()

    token = encode_token(
        subject=str(user.id),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=3600,
        organization_id=str(org.id),
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    _assert_no_secrets_leaked(response.text)
    body = response.json()
    # Explicit typed response model — no raw ORM fields beyond what
    # AuthMeResponse declares.
    assert set(body.keys()) == {
        "user_id",
        "email",
        "organization_id",
        "role",
        "requires_onboarding",
    }


async def test_github_callback_error_response_never_contains_secrets(client):
    response = await client.get("/api/v1/auth/github/callback", params={"error": "access_denied"})
    _assert_no_secrets_leaked(response.text)


async def test_internal_error_response_never_echoes_settings_values(client, monkeypatch):
    from app.api.v1 import health as health_module

    async def _boom(*args, **kwargs):
        settings = get_settings()
        raise RuntimeError(f"db failed near secret={settings.jwt_secret}")

    monkeypatch.setattr(health_module, "check_database", _boom, raising=False)
    response = await client.get("/api/v1/ready")
    _assert_no_secrets_leaked(response.text)
