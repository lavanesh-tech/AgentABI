"""Audit event read API — integration tests (Security Phase E spec §17/
§18/§26). Written and `py_compile`-clean; needs SQLAlchemy/FastAPI/
httpx, unavailable in this sandbox — see docs/DECISIONS.md. Mirrors
`tests/test_organization_isolation_api.py`'s fixture usage.
"""

import uuid

from app.audit.actions import AuditAction
from app.auth.jwt import encode_token
from app.core.config import get_settings
from app.services.audit_service import AuditService


async def _make_org_with_member(session, *, role):
    from app.models import Organization, OrganizationMember, User

    settings = get_settings()
    user = User(email=f"{uuid.uuid4().hex[:8]}@example.com", full_name="Test", is_active=True)
    session.add(user)
    await session.flush()
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
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
    return org, user, token


async def test_owner_can_read_audit_events(client, session):
    from app.models.organization_member import OrganizationRole

    org, _, token = await _make_org_with_member(session, role=OrganizationRole.OWNER)
    AuditService(session).record(action=AuditAction.LOGIN_SUCCESS, organization_id=org.id)
    await session.commit()

    response = await client.get(
        f"/api/v1/organizations/{org.id}/audit-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 1


async def test_admin_can_read_audit_events(client, session):
    from app.models.organization_member import OrganizationRole

    org, _, token = await _make_org_with_member(session, role=OrganizationRole.ADMIN)
    response = await client.get(
        f"/api/v1/organizations/{org.id}/audit-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


async def test_member_is_denied(client, session):
    from app.models.organization_member import OrganizationRole

    org, _, token = await _make_org_with_member(session, role=OrganizationRole.MEMBER)
    response = await client.get(
        f"/api/v1/organizations/{org.id}/audit-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


async def test_cross_organization_access_is_denied(client, session):
    from app.models.organization_member import OrganizationRole

    _, _, token = await _make_org_with_member(session, role=OrganizationRole.OWNER)
    other_org, _, _ = await _make_org_with_member(session, role=OrganizationRole.OWNER)

    response = await client.get(
        f"/api/v1/organizations/{other_org.id}/audit-events",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


async def test_pagination_params_are_respected(client, session):
    from app.models.organization_member import OrganizationRole

    org, _, token = await _make_org_with_member(session, role=OrganizationRole.OWNER)
    for _ in range(3):
        AuditService(session).record(action=AuditAction.SCAN_TRIGGERED, organization_id=org.id)
    await session.commit()

    response = await client.get(
        f"/api/v1/organizations/{org.id}/audit-events",
        params={"page": 1, "page_size": 2},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 3
