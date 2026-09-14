"""GitHub repository mapping management API (Phase 12 spec §33/§34).
Routes never touch the ORM/repositories directly — business rules
(duplicate-repository detection, tenant scoping) live in
`GitHubRepositoryMappingService`. Domain exceptions translate to HTTP
responses centrally in `app/api/v1/errors.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.authz.permissions import Permission
from app.core.database import get_db_session
from app.models.github_repository_mapping import GitHubRepositoryMapping
from app.services.github_repository_mapping_service import GitHubRepositoryMappingService

router = APIRouter(prefix="/projects/{project_id}/github/repositories", tags=["github"])

_READ = Depends(require_project_permission(Permission.GITHUB_INTEGRATION_READ))
_MANAGE = Depends(require_project_permission(Permission.GITHUB_INTEGRATION_MANAGE))


class GitHubRepositoryMappingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    github_repository_id: int = Field(gt=0)
    github_repository_full_name: str = Field(min_length=1, max_length=255)
    github_installation_id: int | None = Field(default=None, gt=0)
    component_id: uuid.UUID | None = None
    baseline_version: str | None = Field(default=None, max_length=50)


class GitHubRepositoryMappingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    component_id: uuid.UUID | None
    github_repository_id: int
    github_repository_full_name: str
    github_installation_id: int | None
    baseline_version: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: GitHubRepositoryMapping) -> "GitHubRepositoryMappingResponse":
        return cls(
            id=record.id,
            project_id=record.project_id,
            component_id=record.component_id,
            github_repository_id=record.github_repository_id,
            github_repository_full_name=record.github_repository_full_name,
            github_installation_id=record.github_installation_id,
            baseline_version=record.baseline_version,
            created_at=record.created_at,
        )


class GitHubRepositoryMappingListResponse(BaseModel):
    items: list[GitHubRepositoryMappingResponse]


def get_mapping_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GitHubRepositoryMappingService:
    return GitHubRepositoryMappingService(session)


ServiceDep = Annotated[GitHubRepositoryMappingService, Depends(get_mapping_service)]


@router.post(
    "",
    response_model=GitHubRepositoryMappingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_MANAGE],
    summary="Map a GitHub repository to this project",
    description="Requires ADMIN or OWNER. Keyed by GitHub's immutable "
    "numeric repository id — a repository already mapped elsewhere is "
    "rejected as a conflict.",
)
async def create_repository_mapping(
    project_id: uuid.UUID,
    payload: GitHubRepositoryMappingCreateRequest,
    service: ServiceDep,
) -> GitHubRepositoryMappingResponse:
    mapping = await service.create_mapping(
        project_id,
        github_repository_id=payload.github_repository_id,
        github_repository_full_name=payload.github_repository_full_name,
        github_installation_id=payload.github_installation_id,
        component_id=payload.component_id,
        baseline_version=payload.baseline_version,
    )
    return GitHubRepositoryMappingResponse.from_record(mapping)


@router.get("", response_model=GitHubRepositoryMappingListResponse, dependencies=[_READ])
async def list_repository_mappings(
    project_id: uuid.UUID, service: ServiceDep
) -> GitHubRepositoryMappingListResponse:
    items = await service.list_mappings(project_id)
    return GitHubRepositoryMappingListResponse(
        items=[GitHubRepositoryMappingResponse.from_record(m) for m in items]
    )


@router.delete(
    "/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_MANAGE],
    summary="Remove a GitHub repository mapping",
)
async def delete_repository_mapping(
    project_id: uuid.UUID, mapping_id: uuid.UUID, service: ServiceDep
) -> None:
    await service.delete_mapping(project_id, mapping_id)
