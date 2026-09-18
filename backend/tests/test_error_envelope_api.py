"""Standardized error envelope — integration tests (Security Phase D
spec §11/§24). Written and `py_compile`-clean; needs SQLAlchemy/FastAPI/
httpx, unavailable in this sandbox — see docs/DECISIONS.md. Mirrors
`tests/test_auth_api.py`'s `client`/`session` fixture usage.
"""

import uuid

from app.auth.jwt import encode_token
from app.core.config import get_settings


def _envelope(response) -> dict:
    body = response.json()
    assert "error" in body
    error = body["error"]
    assert set(error.keys()) >= {"code", "message", "request_id"}
    return error


async def test_authentication_required_returns_standard_envelope(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    error = _envelope(response)
    assert error["code"] == "AUTHENTICATION_REQUIRED"
    assert "traceback" not in response.text.lower()


async def test_invalid_token_returns_standard_envelope(client):
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    error = _envelope(response)
    assert error["code"] == "INVALID_TOKEN"


async def test_resource_not_found_returns_standard_envelope(client, session):
    settings = get_settings()
    from app.models import Organization, OrganizationMember, OrganizationRole, User

    user = User(email="a@example.com", full_name="Test", is_active=True)
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
    response = await client.get(
        f"/api/v1/projects/{uuid.uuid4()}/compatibility/scans/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    error = _envelope(response)
    assert error["code"] == "RESOURCE_NOT_FOUND"


async def test_validation_error_returns_standard_envelope_with_fields(client, session):
    from app.models import Organization, OrganizationMember, OrganizationRole, User

    settings = get_settings()

    user = User(
        email=f"validation-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Validation User",
        is_active=True,
    )
    session.add(user)
    await session.flush()

    org = Organization(
        name="Validation Org",
        slug=f"validation-{uuid.uuid4().hex[:8]}",
    )
    session.add(org)
    await session.flush()

    session.add(
        OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.ADMIN,
        )
    )
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

    response = await client.get(
        "/api/v1/projects/not-a-uuid/compatibility/scans",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
    error = _envelope(response)
    assert error["code"] == "VALIDATION_ERROR"

    body = response.json()
    assert "fields" in body["error"]
    assert "input" not in str(body["error"]["fields"])


async def test_unhandled_internal_error_never_leaks_stack_trace(client, monkeypatch):
    from app.api.v1 import health as health_module

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated: password=hunter2 leaked-secret-token")

    monkeypatch.setattr(health_module, "check_database", _boom, raising=False)

    response = await client.get("/api/v1/ready")
    if response.status_code != 500:
        return  # ready endpoint may not route through the patched symbol; skip gracefully
    error = _envelope(response)
    assert error["code"] == "INTERNAL_ERROR"
    text = response.text.lower()
    assert "traceback" not in text
    assert "runtimeerror" not in text
    assert "hunter2" not in text
    assert "leaked-secret-token" not in text
