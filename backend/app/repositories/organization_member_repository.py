"""Persistence access for OrganizationMember. Used by the authentication
dependency to resolve a user's *current* role for a given organization —
always reloaded per request, never trusted from a JWT (see
`app/auth/claims.py`)."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization_member import OrganizationMember


class OrganizationMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_user_and_organization(
        self, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> OrganizationMember | None:
        stmt = select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.organization_id == organization_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[OrganizationMember]:
        """Used by the GitHub OAuth callback (Security Phase B) to decide
        whether an org context can be attached to the issued JWT: exactly
        one membership -> that org; zero or many -> `organization_id=None`
        (see `app/services/github_oauth_service.py`)."""
        stmt = select(OrganizationMember).where(OrganizationMember.user_id == user_id)
        return (await self._session.execute(stmt)).scalars().all()

    def add(self, member: OrganizationMember) -> None:
        self._session.add(member)
