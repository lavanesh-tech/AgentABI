"""Persistence access for Organization. Mirrors `ProjectRepository`'s
thin shape — lookups plus a sync `add()`, no business logic (that lives
in `OrganizationService`)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization
from app.models.user import User


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_slug(self, slug: str) -> Organization | None:
        stmt = select(Organization).where(Organization.slug == slug)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def lock_user_for_onboarding(self, user_id: uuid.UUID) -> User | None:
        """Take a row-level lock (`SELECT ... FOR UPDATE`) on the caller's
        own `User` row before checking/creating their first organization.

        Why: the DB-level `uq_organization_members_org_user` constraint
        only stops a user from getting two memberships in the *same*
        organization — it does nothing to stop two concurrent onboarding
        requests for the *same user* from each independently observing
        zero memberships and each creating a *different* new organization
        (task requirement: "concurrent duplicate onboarding attempts must
        not produce duplicate organizations"). Locking the user's own row
        for the duration of the check-then-create serializes concurrent
        onboarding attempts for that one user without taking any lock
        that could block unrelated users or unrelated requests."""

        stmt = select(User).where(User.id == user_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def add(self, organization: Organization) -> None:
        self._session.add(organization)
