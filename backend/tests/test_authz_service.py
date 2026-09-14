"""AuthorizationService — integration tests (real Postgres via `client`/
`session` fixtures, Security Phase C spec §22/§25/§26). Written and
`py_compile`-clean; needs SQLAlchemy, unavailable in this sandbox — same
bucket as test_replay_service.py (DECISIONS.md ADR-036).
"""

import uuid

import pytest

from app.authz.permissions import Permission
from app.authz.service import AuthorizationService
from app.domain.exceptions import (
    OrganizationAccessDenied,
    PermissionDenied,
    ProjectAccessDenied,
    ProjectNotFound,
)
from app.models import Organization, OrganizationMember, OrganizationRole, Project, User


async def _make_user(session, *, email="a@example.com") -> User:
    user = User(email=email, full_name="Test User", is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _make_org_with_member(session, user, *, role=OrganizationRole.MEMBER):
    org = Organization(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    member = OrganizationMember(organization_id=org.id, user_id=user.id, role=role)
    session.add(member)
    project = Project(organization_id=org.id, name="Payments", slug="payments")
    session.add(project)
    await session.flush()
    await session.commit()
    return org, member, project


def _principal(user, *, organization_id=None, role=None):
    from app.auth.principal import AuthenticatedPrincipal

    return AuthenticatedPrincipal(
        user_id=user.id, email=user.email, organization_id=organization_id, role=role
    )


async def test_project_access_granted_for_member_with_read_permission(session):
    user = await _make_user(session)
    org, member, project = await _make_org_with_member(session, user, role=OrganizationRole.MEMBER)
    service = AuthorizationService(session)
    resolved_project, resolved_member = await service.authorize_project_access(
        principal=_principal(user), project_id=project.id, permission=Permission.PROJECT_READ
    )
    assert resolved_project.id == project.id
    assert resolved_member.role == OrganizationRole.MEMBER


async def test_project_access_denied_for_member_write_permission(session):
    user = await _make_user(session)
    org, member, project = await _make_org_with_member(session, user, role=OrganizationRole.MEMBER)
    service = AuthorizationService(session)
    with pytest.raises(PermissionDenied):
        await service.authorize_project_access(
            principal=_principal(user), project_id=project.id, permission=Permission.PROJECT_UPDATE
        )


async def test_project_access_denied_for_nonexistent_project(session):
    user = await _make_user(session)
    service = AuthorizationService(session)
    with pytest.raises(ProjectNotFound):
        await service.authorize_project_access(
            principal=_principal(user), project_id=uuid.uuid4(), permission=Permission.PROJECT_READ
        )


async def test_cross_org_project_access_denied(session):
    """User A (org A member) must not access org B's project, even
    knowing its UUID directly — spec §22 "direct-resource UUID
    guessing"."""
    user_a = await _make_user(session, email="a@example.com")
    await _make_org_with_member(session, user_a, role=OrganizationRole.ADMIN)

    user_b = await _make_user(session, email="b@example.com")
    _, _, project_b = await _make_org_with_member(session, user_b, role=OrganizationRole.OWNER)

    service = AuthorizationService(session)
    with pytest.raises(ProjectAccessDenied):
        await service.authorize_project_access(
            principal=_principal(user_a),
            project_id=project_b.id,
            permission=Permission.PROJECT_READ,
        )


async def test_organization_access_denied_with_no_membership(session):
    user = await _make_user(session)
    service = AuthorizationService(session)
    with pytest.raises(OrganizationAccessDenied):
        await service.authorize_organization_access(
            principal=_principal(user),
            organization_id=uuid.uuid4(),
            permission=Permission.PROJECT_READ,
        )


async def test_stale_jwt_role_reflects_current_db_state(session):
    """Spec §25: a still-valid JWT issued while the user was ADMIN must
    yield MEMBER-level authorization once the DB role is downgraded,
    without reissuing the token — proves ADR-038/041 in practice."""
    user = await _make_user(session)
    org, member, project = await _make_org_with_member(session, user, role=OrganizationRole.ADMIN)
    principal = _principal(user, organization_id=org.id, role=OrganizationRole.ADMIN)
    service = AuthorizationService(session)

    # Same still-valid principal, before the DB change: ADMIN write succeeds.
    await service.authorize_project_access(
        principal=principal, project_id=project.id, permission=Permission.PROJECT_UPDATE
    )

    # Role changed in the DB; the principal object (standing in for the
    # unchanged JWT) is reused unmodified.
    member.role = OrganizationRole.MEMBER
    await session.commit()

    with pytest.raises(PermissionDenied):
        await service.authorize_project_access(
            principal=principal, project_id=project.id, permission=Permission.PROJECT_UPDATE
        )
    # Reads still work, at MEMBER level.
    await service.authorize_project_access(
        principal=principal, project_id=project.id, permission=Permission.PROJECT_READ
    )


async def test_membership_removal_denies_access_immediately(session):
    """Spec §26: removing the membership row must deny access on the
    very next request, even though the JWT itself is still
    cryptographically valid and unexpired."""
    user = await _make_user(session)
    org, member, project = await _make_org_with_member(session, user, role=OrganizationRole.MEMBER)
    principal = _principal(user, organization_id=org.id, role=OrganizationRole.MEMBER)
    service = AuthorizationService(session)

    await service.authorize_project_access(
        principal=principal, project_id=project.id, permission=Permission.PROJECT_READ
    )

    await session.delete(member)
    await session.commit()

    with pytest.raises(ProjectAccessDenied):
        await service.authorize_project_access(
            principal=principal, project_id=project.id, permission=Permission.PROJECT_READ
        )
