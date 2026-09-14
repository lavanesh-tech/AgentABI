"""Persistence access for Project. Used by the component registry and
authorization services to validate that a project exists (and, for
`AuthorizationService`, to learn its `organization_id`) before scoping
queries to it. Minimal CRUD added in Security Phase C purely as an
authorization-testing surface (spec §10) — this is not a general project
management API."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        stmt = select(Project).where(Project.id == project_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_for_organization(
        self, project_id: uuid.UUID, organization_id: uuid.UUID
    ) -> Project | None:
        """Ownership-aware lookup (spec §28): a single query scoped by
        both `id` and `organization_id`, rather than fetching by `id`
        and checking `organization_id` afterward. Not used by
        `AuthorizationService` itself (which must learn `organization_id`
        *from* the project, since only `project_id` is known at that
        point — see its docstring), but available to any future
        caller that already knows both."""

        stmt = select(Project).where(
            Project.id == project_id, Project.organization_id == organization_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_slug(self, organization_id: uuid.UUID, slug: str) -> Project | None:
        stmt = select(Project).where(
            Project.organization_id == organization_id, Project.slug == slug
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_organization(
        self, organization_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[Sequence[Project], int]:
        filters = [Project.organization_id == organization_id]
        count_stmt = select(func.count()).select_from(Project).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Project)
            .where(*filters)
            .order_by(Project.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = (await self._session.execute(stmt)).scalars().all()
        return items, total

    def add(self, project: Project) -> None:
        self._session.add(project)
