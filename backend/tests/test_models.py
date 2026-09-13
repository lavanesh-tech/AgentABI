"""ORM model constraint tests — integration tests against a real Postgres
(see the `db_engine` fixture in conftest.py): uniqueness, foreign keys,
cascade deletes, and server-side defaults are all enforced by Postgres
itself, so these tests prove the constraints actually work, not just that
SQLAlchemy accepted the mapping.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import get_session_factory
from app.models import Organization, OrganizationMember, OrganizationRole, Project, User


@pytest.fixture
def session_factory(db_engine):
    return get_session_factory()


async def test_organization_defaults_are_server_generated(session_factory):
    async with session_factory() as session:
        org = Organization(name="Acme", slug="acme")
        session.add(org)
        await session.commit()
        await session.refresh(org)

        assert org.id is not None
        assert org.created_at is not None
        assert org.updated_at is not None


async def test_organization_slug_must_be_unique(session_factory):
    async with session_factory() as session:
        session.add(Organization(name="Acme", slug="acme"))
        await session.commit()

    async with session_factory() as session:
        session.add(Organization(name="Acme Duplicate", slug="acme"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_project_slug_unique_per_organization_not_globally(session_factory):
    async with session_factory() as session:
        org_a = Organization(name="Acme", slug="acme")
        org_b = Organization(name="Globex", slug="globex")
        session.add_all([org_a, org_b])
        await session.flush()

        session.add(Project(organization_id=org_a.id, name="Payments", slug="payments"))
        session.add(Project(organization_id=org_b.id, name="Payments", slug="payments"))
        # Same slug under two different organizations is allowed.
        await session.commit()

        session.add(Project(organization_id=org_a.id, name="Payments Dup", slug="payments"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_organization_member_role_defaults_to_member(session_factory):
    async with session_factory() as session:
        org = Organization(name="Acme", slug="acme")
        user = User(email="lav@example.com")
        session.add_all([org, user])
        await session.flush()

        membership = OrganizationMember(organization_id=org.id, user_id=user.id)
        session.add(membership)
        await session.commit()
        await session.refresh(membership)

        assert membership.role == OrganizationRole.MEMBER


async def test_deleting_organization_cascades_to_projects_and_memberships(session_factory):
    async with session_factory() as session:
        org = Organization(name="Acme", slug="acme")
        user = User(email="lav@example.com")
        session.add_all([org, user])
        await session.flush()

        session.add(Project(organization_id=org.id, name="Payments", slug="payments"))
        session.add(OrganizationMember(organization_id=org.id, user_id=user.id))
        await session.commit()

    async with session_factory() as session:
        org = (
            await session.execute(select(Organization).where(Organization.slug == "acme"))
        ).scalar_one()
        await session.delete(org)
        await session.commit()

    async with session_factory() as session:
        remaining_projects = (await session.execute(select(Project))).scalars().all()
        remaining_memberships = (await session.execute(select(OrganizationMember))).scalars().all()
        assert remaining_projects == []
        assert remaining_memberships == []
