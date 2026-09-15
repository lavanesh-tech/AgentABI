"""First-organization onboarding API — integration tests (`POST
/organizations`). Written and `py_compile`-clean; needs FastAPI/httpx/
SQLAlchemy, unavailable in this sandbox — same bucket as every other
`tests/test_*_api.py` file (see README/DECISIONS.md for the sandbox's
PyPI-403 constraint). Mirrors `test_organization_isolation_api.py`'s
fixture shape.
"""

import uuid

from sqlalchemy import select

from app.auth.jwt import decode_token, encode_token
from app.core.config import get_settings
from app.models import Organization, OrganizationMember, OrganizationRole, User


async def _make_user(session, email: str) -> User:
    user = User(email=email, full_name="Test User", is_active=True)
    session.add(user)
    await session.flush()
    await session.commit()
    return user


def _token_for(user_id, *, organization_id=None) -> str:
    settings = get_settings()
    return encode_token(
        subject=str(user_id),
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        expires_in_seconds=3600,
        organization_id=str(organization_id) if organization_id else None,
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Authentication ---------------------------------------------------------


async def test_unauthenticated_create_organization_rejected(client, session):
    response = await client.post("/api/v1/organizations", json={"name": "Acme"})
    assert response.status_code == 401
    body = response.json()
    assert "error" in body  # standardized envelope, even for auth failures


# --- Happy path --------------------------------------------------------------


async def test_orgless_user_can_create_first_organization(client, session):
    user = await _make_user(session, "orgless@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations", json={"name": "Acme Inc."}, headers=_auth(token)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["organization_name"] == "Acme Inc."
    assert body["role"] == OrganizationRole.OWNER.value
    assert body["access_token"]


async def test_caller_becomes_owner_of_newly_created_organization(client, session):
    user = await _make_user(session, "owner@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations", json={"name": "Acme"}, headers=_auth(token)
    )
    assert response.status_code == 201
    organization_id = uuid.UUID(response.json()["organization_id"])

    stmt = select(OrganizationMember).where(
        OrganizationMember.organization_id == organization_id,
        OrganizationMember.user_id == user.id,
    )
    membership = (await session.execute(stmt)).scalar_one()
    assert membership.role == OrganizationRole.OWNER


async def test_organization_and_membership_created_atomically(client, session):
    user = await _make_user(session, "atomic@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations", json={"name": "Atomic Co"}, headers=_auth(token)
    )
    assert response.status_code == 201
    organization_id = uuid.UUID(response.json()["organization_id"])

    org = (
        await session.execute(select(Organization).where(Organization.id == organization_id))
    ).scalar_one_or_none()
    assert org is not None
    member_count = (
        (
            await session.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == organization_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(member_count) == 1


# --- Request body cannot escalate privilege ----------------------------------


async def test_caller_cannot_select_arbitrary_role(client, session):
    user = await _make_user(session, "role@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Acme", "role": "owner"},
        headers=_auth(token),
    )
    assert response.status_code == 422  # extra="forbid" rejects the field outright


async def test_caller_cannot_assign_another_user_as_owner(client, session):
    user = await _make_user(session, "caller@example.com")
    other = await _make_user(session, "victim@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Acme", "user_id": str(other.id), "owner_id": str(other.id)},
        headers=_auth(token),
    )
    assert response.status_code == 422

    # The other user still has no membership anywhere.
    stmt = select(OrganizationMember).where(OrganizationMember.user_id == other.id)
    assert (await session.execute(stmt)).scalar_one_or_none() is None


async def test_caller_cannot_provide_organization_id(client, session):
    user = await _make_user(session, "orgid@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations",
        json={"name": "Acme", "organization_id": str(uuid.uuid4())},
        headers=_auth(token),
    )
    assert response.status_code == 422


# --- Already-onboarded caller -------------------------------------------------


async def test_already_onboarded_user_cannot_onboard_again(client, session):
    user = await _make_user(session, "twice@example.com")
    token = _token_for(user.id)

    first = await client.post(
        "/api/v1/organizations", json={"name": "First Org"}, headers=_auth(token)
    )
    assert first.status_code == 201

    second = await client.post(
        "/api/v1/organizations", json={"name": "Second Org"}, headers=_auth(token)
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"]["code"] == "CONFLICT"


async def test_repeated_onboarding_does_not_create_duplicate_organizations(client, session):
    user = await _make_user(session, "repeat@example.com")
    token = _token_for(user.id)

    for _ in range(3):
        await client.post(
            "/api/v1/organizations", json={"name": "Repeat Org"}, headers=_auth(token)
        )

    stmt = select(OrganizationMember).where(OrganizationMember.user_id == user.id)
    memberships = (await session.execute(stmt)).scalars().all()
    assert len(memberships) == 1


# --- Cross-tenant isolation ----------------------------------------------------


async def test_two_users_onboarding_get_distinct_organizations(client, session):
    user_a = await _make_user(session, "a-onboard@example.com")
    user_b = await _make_user(session, "b-onboard@example.com")
    token_a = _token_for(user_a.id)
    token_b = _token_for(user_b.id)

    response_a = await client.post(
        "/api/v1/organizations", json={"name": "Org A"}, headers=_auth(token_a)
    )
    response_b = await client.post(
        "/api/v1/organizations", json={"name": "Org B"}, headers=_auth(token_b)
    )
    assert response_a.status_code == 201
    assert response_b.status_code == 201
    assert response_a.json()["organization_id"] != response_b.json()["organization_id"]


# --- Fresh auth context / token ------------------------------------------------


async def test_fresh_token_carries_new_organization_context(client, session):
    user = await _make_user(session, "freshtoken@example.com")
    token = _token_for(user.id)

    response = await client.post(
        "/api/v1/organizations", json={"name": "Fresh Co"}, headers=_auth(token)
    )
    assert response.status_code == 201
    body = response.json()

    settings = get_settings()
    claims = decode_token(
        body["access_token"],
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    assert claims.org_id == body["organization_id"]
    # Role is never carried in the token — only org_id (see app/auth/jwt.py).
    payload_keys = {"sub", "iss", "aud", "iat", "exp", "org_id"}
    assert set(claims.to_payload().keys()) <= payload_keys


async def test_new_token_reflects_owner_role_via_auth_me(client, session):
    user = await _make_user(session, "meafter@example.com")
    token = _token_for(user.id)

    onboarding = await client.post(
        "/api/v1/organizations", json={"name": "Me Co"}, headers=_auth(token)
    )
    fresh_token = onboarding.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers=_auth(fresh_token))
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == OrganizationRole.OWNER.value
    assert body["requires_onboarding"] is False


# --- /auth/me requires_onboarding (task §2/§7: authoritative, not just the
# one-time OAuth callback flag) -------------------------------------------


async def test_auth_me_requires_onboarding_true_for_orgless_user(client, session):
    user = await _make_user(session, "needsonboarding@example.com")
    token = _token_for(user.id)

    response = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["requires_onboarding"] is True


async def test_auth_me_requires_onboarding_false_after_onboarding(client, session):
    user = await _make_user(session, "afteronboarding@example.com")
    token = _token_for(user.id)
    await client.post("/api/v1/organizations", json={"name": "Later Co"}, headers=_auth(token))

    # Even the *original* (pre-onboarding) token — which has no org_id
    # claim — still reflects the authoritative, freshly reloaded state,
    # because /auth/me recomputes `requires_onboarding` from the
    # database rather than trusting anything in the token.
    response = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["requires_onboarding"] is False
