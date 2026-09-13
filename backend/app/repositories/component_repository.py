"""Persistence access for Component. Deliberately thin — no business rules
here (duplicate checking, tenant validation, etc. live in
`ComponentRegistryService`); this just translates between the ORM and
simple, domain-shaped queries, always scoped by `project_id` so a caller
cannot accidentally fetch a component belonging to another project.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import ComponentType
from app.models.component import Component


class ComponentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID, component_id: uuid.UUID) -> Component | None:
        stmt = select(Component).where(
            Component.id == component_id, Component.project_id == project_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(
        self, project_id: uuid.UUID, component_type: ComponentType, slug: str
    ) -> Component | None:
        stmt = select(Component).where(
            Component.project_id == project_id,
            Component.component_type == component_type,
            Component.slug == slug,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        component_type: ComponentType | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Component], int]:
        filters = [Component.project_id == project_id]
        if component_type is not None:
            filters.append(Component.component_type == component_type)

        count_stmt = select(func.count()).select_from(Component).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Component)
            .where(*filters)
            .order_by(Component.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    def add(self, component: Component) -> None:
        self._session.add(component)
