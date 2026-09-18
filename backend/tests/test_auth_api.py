"""Authentication API/dependency — integration tests (real Postgres via
`client` + `session` fixtures). Written and `py_compile`-clean; needs
SQLAlchemy/FastAPI/httpx, unavailable in this sandbox — see
docs/DECISIONS.md."""

import uuid

from app.auth.jwt import encode_token
from app.core.config import get_settings
from app.models import Organization, OrganizationMember, OrganizationRole, User


async def _make_user(session, *, email="a@example.com", is_active=True) -> User:
    user = User(email=email, full_name="Test User", is_active=is_active)
    session.add(user)
    await session.flush()
    await session.commit()
    return user


async def _make_membership(session, user, *, role=OrganizationRole.ADMIN):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    session.add(member)
    await session.flush()
    await session.commit()
    return org, member


def _token_for(user, *, organization_id=None, expires_in_seconds=3600):
    settings = get_settings()
    return encode_token(
        subject=str(user.id),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=expires_in_seconds,
        organization_id=str(organization_id) if organization_id else None,
    )


async def test_me_without_token_returns_401(client, session):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


async def test_me_with_valid_token_returns_user(client, session):
    user = await _make_user(session)
    org, member = await _make_membership(session, user)
    token = _token_for(user, organization_id=org.id)

    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["email"] == user.email
    assert body["organization_id"] == str(org.id)
    assert body["role"] == member.role.value


async def test_me_response_never_exposes_secret_fields(client, session):
    user = await _make_user(session)
    token = _token_for(user)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    body = response.json()
    assert set(body.keys()) == {
        "user_id",
        "email",
        "organization_id",
        "role",
        "requires_onboarding",
    }


async def test_me_with_expired_token_returns_401(client, session):
    user = await _make_user(session)
    token = _token_for(user, expires_in_seconds=-10)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_me_with_malformed_token_returns_401(client, session):
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_me_for_unknown_user_returns_401(client, session):
    settings = get_settings()
    token = encode_token(
        subject=str(uuid.uuid4()),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=3600,
    )
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_me_for_disabled_user_returns_401(client, session):
    user = await _make_user(session, is_active=False)
    token = _token_for(user)
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_me_with_org_id_the_user_does_not_belong_to_has_no_role(client, session):
    user = await _make_user(session)
    token = _token_for(user, organization_id=uuid.uuid4())
    response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["role"] is None
