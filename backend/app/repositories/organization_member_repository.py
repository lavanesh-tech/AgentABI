"""Persistence access for OrganizationMember. Used by the authentication
dependency to resolve a user's *current* role for a given organization —
always reloaded per request, never trusted from a JWT (see
`app/auth/claims.py`)."""

import uuid

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
