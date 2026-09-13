"""Persistence access for ComponentVersion. As thin as
ComponentRepository — no duplicate-checking or validation logic here."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.component_version import ComponentVersion


class ComponentVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_version(
        self, component_id: uuid.UUID, version: str
    ) -> ComponentVersion | None:
        stmt = select(ComponentVersion).where(
            ComponentVersion.component_id == component_id,
            ComponentVersion.version == version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_latest(self, component_id: uuid.UUID) -> ComponentVersion | None:
        stmt = (
            select(ComponentVersion)
            .where(ComponentVersion.component_id == component_id)
            .order_by(ComponentVersion.sequence.desc())
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_component(
        self, component_id: uuid.UUID, offset: int, limit: int
    ) -> tuple[list[ComponentVersion], int]:
        count_stmt = (
            select(func.count())
            .select_from(ComponentVersion)
            .where(ComponentVersion.component_id == component_id)
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ComponentVersion)
            .where(ComponentVersion.component_id == component_id)
            .order_by(ComponentVersion.sequence.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    def add(self, version: ComponentVersion) -> None:
        self._session.add(version)
