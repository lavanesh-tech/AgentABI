"""Persistence access for Project. Used by the component registry service
only to validate that a project exists before scoping queries to it — full
project CRUD is out of this phase's scope."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, project_id: uuid.UUID) -> Project | None:
        stmt = select(Project).where(Project.id == project_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()
