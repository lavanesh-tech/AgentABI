"""Persistence access for `GitHubPullRequestAnalysis` (Phase 12 spec
§22/§23). `get_by_idempotency_key` is checked first by
`GitHubPullRequestAnalysisService` before any pipeline work runs — a
redelivered webhook for a commit already analyzed reuses the existing
row (spec §23) rather than recomputing or republishing.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.github_pr_analysis import GitHubPullRequestAnalysis


class GitHubPRAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        pull_request_number: int | None = None,
        offset: int,
        limit: int,
    ) -> tuple[list[GitHubPullRequestAnalysis], int]:
        """Phase 14 spec §25/§26 read path: exact-SHA analysis history for
        a project, optionally narrowed to one PR number. Never merges
        rows across `head_sha`s — each row stays its own commit's result
        (spec §25's stale-result protection, extended to this read
        endpoint)."""

        conditions = [GitHubPullRequestAnalysis.project_id == project_id]
        if pull_request_number is not None:
            conditions.append(GitHubPullRequestAnalysis.pull_request_number == pull_request_number)

        count_stmt = select(func.count()).select_from(GitHubPullRequestAnalysis).where(*conditions)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(GitHubPullRequestAnalysis)
            .where(*conditions)
            .order_by(GitHubPullRequestAnalysis.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    async def get_by_idempotency_key(
        self,
        github_repository_id: int,
        pull_request_number: int,
        head_sha: str,
        analysis_version: str,
    ) -> GitHubPullRequestAnalysis | None:
        stmt = select(GitHubPullRequestAnalysis).where(
            GitHubPullRequestAnalysis.github_repository_id == github_repository_id,
            GitHubPullRequestAnalysis.pull_request_number == pull_request_number,
            GitHubPullRequestAnalysis.head_sha == head_sha,
            GitHubPullRequestAnalysis.analysis_version == analysis_version,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(
        self, project_id: uuid.UUID, analysis_id: uuid.UUID
    ) -> GitHubPullRequestAnalysis | None:
        stmt = select(GitHubPullRequestAnalysis).where(
            GitHubPullRequestAnalysis.id == analysis_id,
            GitHubPullRequestAnalysis.project_id == project_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def add(self, analysis: GitHubPullRequestAnalysis) -> None:
        self._session.add(analysis)
