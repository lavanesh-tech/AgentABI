"""GitHub PR-analysis read API (Phase 14 spec §1/§16/§25/§26). The only
gap the Phase 14 frontend inventory found: `GitHubPullRequestAnalysis`
rows were written by the Phase 12/13 webhook pipeline but never exposed
over HTTP. This router adds the minimum read surface needed to render
exact-SHA PR-analysis history — no new business logic, no write path,
no redesign of the existing orchestration service.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.authz.permissions import Permission
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.github.checks_client import HttpxGitHubChecksClient, StaticGitHubCredentialProvider
from app.models.github_pr_analysis import GitHubPullRequestAnalysis
from app.services.github_pr_analysis_service import GitHubPullRequestAnalysisService

router = APIRouter(prefix="/projects/{project_id}/github/pr-analyses", tags=["github"])

_READ = Depends(require_project_permission(Permission.GITHUB_INTEGRATION_READ))


class GitHubPRAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    github_repository_id: int
    pull_request_number: int
    head_sha: str
    base_sha: str
    analysis_version: str
    status: str
    decision: str | None
    compatibility_scan_id: uuid.UUID | None
    risk_assessment_id: uuid.UUID | None
    check_run_id: int | None
    publish_error: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: GitHubPullRequestAnalysis) -> "GitHubPRAnalysisResponse":
        return cls(
            id=record.id,
            project_id=record.project_id,
            github_repository_id=record.github_repository_id,
            pull_request_number=record.pull_request_number,
            head_sha=record.head_sha,
            base_sha=record.base_sha,
            analysis_version=record.analysis_version,
            status=record.status,
            decision=record.decision,
            compatibility_scan_id=record.compatibility_scan_id,
            risk_assessment_id=record.risk_assessment_id,
            check_run_id=record.check_run_id,
            publish_error=record.publish_error,
            completed_at=record.completed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class GitHubPRAnalysisListResponse(BaseModel):
    items: list[GitHubPRAnalysisResponse]
    total: int
    page: int
    page_size: int


def get_pr_analysis_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GitHubPullRequestAnalysisService:
    # `checks_client` is never called on this read-only path (no method
    # below publishes a check); constructed only because the existing
    # service's constructor requires one — cheap, no network I/O, same
    # instantiation `app/api/v1/github_webhook.py` already uses.
    checks_client = HttpxGitHubChecksClient(
        StaticGitHubCredentialProvider(settings.github_checks_token)
    )
    return GitHubPullRequestAnalysisService(session, checks_client=checks_client)


ServiceDep = Annotated[GitHubPullRequestAnalysisService, Depends(get_pr_analysis_service)]


@router.get("", response_model=GitHubPRAnalysisListResponse, dependencies=[_READ])
async def list_pr_analyses(
    project_id: uuid.UUID,
    service: ServiceDep,
    pull_request_number: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> GitHubPRAnalysisListResponse:
    result = await service.list_analyses(
        project_id,
        pull_request_number=pull_request_number,
        page=page,
        page_size=page_size,
    )
    return GitHubPRAnalysisListResponse(
        items=[GitHubPRAnalysisResponse.from_record(r) for r in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get(
    "/{analysis_id}",
    response_model=GitHubPRAnalysisResponse,
    dependencies=[_READ],
)
async def get_pr_analysis(
    project_id: uuid.UUID, analysis_id: uuid.UUID, service: ServiceDep
) -> GitHubPRAnalysisResponse:
    record = await service.get_analysis(project_id, analysis_id)
    return GitHubPRAnalysisResponse.from_record(record)
