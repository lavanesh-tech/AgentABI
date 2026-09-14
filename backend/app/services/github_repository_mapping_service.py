"""GitHubRepositoryMappingService — CRUD for `GitHubRepositoryMapping`,
tenant-scoped exactly like every other project-scoped service (Phase 12
spec §32/§33). Backs the management API
(`app/api/v1/github_repositories.py`); the webhook path never calls
this — it resolves mappings via `GitHubRepositoryMappingRepository.
get_by_github_repository_id` directly (server-side lookup, never a
management-API round trip).
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    DuplicateGitHubRepositoryMapping,
    GitHubRepositoryMappingNotFound,
    ProjectNotFound,
)
from app.models.github_repository_mapping import GitHubRepositoryMapping
from app.repositories.github_repository_mapping_repository import (
    GitHubRepositoryMappingRepository,
)
from app.repositories.project_repository import ProjectRepository


class GitHubRepositoryMappingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._mappings = GitHubRepositoryMappingRepository(session)
        self._projects = ProjectRepository(session)

    async def create_mapping(
        self,
        project_id: uuid.UUID,
        *,
        github_repository_id: int,
        github_repository_full_name: str,
        github_installation_id: int | None = None,
        component_id: uuid.UUID | None = None,
        baseline_version: str | None = None,
    ) -> GitHubRepositoryMapping:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)

        mapping = GitHubRepositoryMapping(
            organization_id=project.organization_id,
            project_id=project_id,
            component_id=component_id,
            github_repository_id=github_repository_id,
            github_repository_full_name=github_repository_full_name,
            github_installation_id=github_installation_id,
            baseline_version=baseline_version,
        )
        self._mappings.add(mapping)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateGitHubRepositoryMapping(github_repository_id) from exc
        await self._session.commit()
        return mapping

    async def list_mappings(self, project_id: uuid.UUID) -> list[GitHubRepositoryMapping]:
        return await self._mappings.list_by_project(project_id)

    async def delete_mapping(self, project_id: uuid.UUID, mapping_id: uuid.UUID) -> None:
        mapping = await self._mappings.get_by_id(project_id, mapping_id)
        if mapping is None:
            raise GitHubRepositoryMappingNotFound(mapping_id)
        await self._mappings.delete(mapping)
        await self._session.commit()
