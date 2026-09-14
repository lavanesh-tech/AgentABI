"""ProjectService — minimal project CRUD (Security Phase C spec §10:
"if project APIs are incomplete, implement only the minimum needed for
authorization testing"). Not a general project-management feature;
`app/api/v1/projects.py` exists so Phase C's authorization dependencies
have real routes to guard and real integration tests to write against.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import DuplicateProject, ProjectNotFound
from app.models.project import Project
from app.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectRepository(session)

    async def create_project(self, *, organization_id: uuid.UUID, name: str, slug: str) -> Project:
        project = Project(organization_id=organization_id, name=name, slug=slug)
        self._projects.add(project)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateProject(organization_id, slug) from exc
        await self._session.refresh(project)
        return project

    async def get_project(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    async def list_projects(
        self, organization_id: uuid.UUID, *, page: int, page_size: int
    ) -> Page[Project]:
        offset = (page - 1) * page_size
        items, total = await self._projects.list_by_organization(
            organization_id, offset=offset, limit=page_size
        )
        return Page(items=list(items), total=total, page=page, page_size=page_size)

    async def update_project(self, project_id: uuid.UUID, *, name: str) -> Project:
        project = await self.get_project(project_id)
        project.name = name
        await self._session.commit()
        await self._session.refresh(project)
        return project
