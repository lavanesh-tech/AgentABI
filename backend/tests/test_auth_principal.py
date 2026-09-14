"""Unit tests for `app/auth/principal.py`. No database/network I/O, but
(unlike `test_auth_jwt.py`) this module imports `OrganizationRole` from
`app.models.organization_member`, which pulls in SQLAlchemy — not
runnable via `pytest --noconftest` in this sandbox (SQLAlchemy is
unavailable here, same restriction as every prior phase's ORM-touching
tests). Written and `py_compile`-clean."""

import uuid

from app.auth.principal import AuthenticatedPrincipal
from app.models.organization_member import OrganizationRole


def test_principal_construction_with_role():
    principal = AuthenticatedPrincipal(
        user_id=uuid.uuid4(),
        email="a@example.com",
        organization_id=uuid.uuid4(),
        role=OrganizationRole.ADMIN,
    )
    assert principal.role == OrganizationRole.ADMIN


def test_principal_construction_without_organization():
    principal = AuthenticatedPrincipal(
        user_id=uuid.uuid4(), email="a@example.com", organization_id=None, role=None
    )
    assert principal.organization_id is None
    assert principal.role is None
