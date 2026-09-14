"""Persistence access for `GitHubRepositoryMapping` (Phase 12 spec
§7/§32). `get_by_github_repository_id` is the ONLY resolution path a
webhook uses — server-side lookup by GitHub's immutable numeric id,
never trusting any project/org identifier the webhook payload itself
might carry (spec §32's tenant-isolation requirement)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github_repository_mapping import GitHubRepositoryMapping


class GitHubRepositoryMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_github_repository_id(
        self, github_repository_id: int
    ) -> GitHubRepositoryMapping | None:
        stmt = select(GitHubRepositoryMapping).where(
            GitHubRepositoryMapping.github_repository_id == github_repository_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(
        self, project_id: uuid.UUID, mapping_id: uuid.UUID
    ) -> GitHubRepositoryMapping | None:
        stmt = select(GitHubRepositoryMapping).where(
            GitHubRepositoryMapping.id == mapping_id,
            GitHubRepositoryMapping.project_id == project_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(self, project_id: uuid.UUID) -> list[GitHubRepositoryMapping]:
        stmt = (
            select(GitHubRepositoryMapping)
            .where(GitHubRepositoryMapping.project_id == project_id)
            .order_by(GitHubRepositoryMapping.created_at.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    def add(self, mapping: GitHubRepositoryMapping) -> None:
        self._session.add(mapping)

    async def delete(self, mapping: GitHubRepositoryMapping) -> None:
        await self._session.delete(mapping)
