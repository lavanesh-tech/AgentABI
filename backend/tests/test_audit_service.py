"""AuditService — integration tests (Security Phase E spec §26). Written
and `py_compile`-clean; needs SQLAlchemy, unavailable in this sandbox —
see docs/DECISIONS.md.
"""

import uuid

import pytest

from app.audit.actions import AuditAction
from app.models import Organization
from app.services.audit_service import AuditService


async def test_record_appends_and_is_queryable(session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    org_id = org.id
    service = AuditService(session)
    service.record(
        action=AuditAction.PROJECT_CREATED,
        organization_id=org_id,
        resource_type="project",
        resource_id=uuid.uuid4(),
        metadata={"slug": "demo"},
    )
    await session.commit()

    page = await service.list_events(org_id)
    assert page.total == 1
    assert page.items[0].action == AuditAction.PROJECT_CREATED


async def test_metadata_is_redacted(session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    org_id = org.id
    service = AuditService(session)
    service.record(
        action=AuditAction.LOGIN_FAILURE,
        organization_id=org_id,
        metadata={"reason": "bad", "authorization": "Bearer fake-jwt-value"},
    )
    await session.commit()

    page = await service.list_events(org_id)
    assert page.items[0].audit_metadata["authorization"] == "***REDACTED***"


async def test_immutable_update_is_rejected(session):
    from sqlalchemy.exc import DBAPIError

    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    org_id = org.id
    service = AuditService(session)
    event = service.record(action=AuditAction.LOGIN_SUCCESS, organization_id=org_id)
    await session.commit()

    event.resource_type = "tampered"
    with pytest.raises(DBAPIError):
        await session.commit()


async def test_tenant_scoping_excludes_other_organizations(session):
    org_a_row = Organization(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:8]}")
    org_b_row = Organization(name="Org B", slug=f"org-b-{uuid.uuid4().hex[:8]}")
    session.add_all([org_a_row, org_b_row])
    await session.flush()
    org_a = org_a_row.id
    org_b = org_b_row.id
    service = AuditService(session)
    service.record(action=AuditAction.LOGIN_SUCCESS, organization_id=org_a)
    service.record(action=AuditAction.LOGIN_SUCCESS, organization_id=org_b)
    await session.commit()

    page_a = await service.list_events(org_a)
    assert page_a.total == 1


async def test_pagination(session):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    org_id = org.id
    service = AuditService(session)
    for _ in range(5):
        service.record(action=AuditAction.SCAN_TRIGGERED, organization_id=org_id)
    await session.commit()

    page = await service.list_events(org_id, page=1, page_size=2)
    assert len(page.items) == 2
    assert page.total == 5
