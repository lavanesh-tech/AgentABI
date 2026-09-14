"""Project API — minimal CRUD (Security Phase C spec §10). Exists to
give the new authorization dependencies (`app/api/deps/authz.py`) real
routes to guard: MEMBER can read, only ADMIN/OWNER can create/update,
list is scoped to organizations the caller belongs to (never all
projects globally). Not a general project-management feature — see
`app/services/project_service.py`.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_organization_permission, require_project_permission
from app.authz.permissions import Permission
from app.core.database import get_db_session
from app.models.project import Project
from app.services.project_service import ProjectService

router = APIRouter(tags=["projects"])

_SLUG_PATTERN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"

_ORG_READ = Depends(require_organization_permission(Permission.PROJECT_READ))
_ORG_CREATE = Depends(require_organization_permission(Permission.PROJECT_CREATE))
_PROJECT_READ = Depends(require_project_permission(Permission.PROJECT_READ))
_PROJECT_UPDATE = Depends(require_project_permission(Permission.PROJECT_UPDATE))


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100, pattern=_SLUG_PATTERN)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    page: int
    page_size: int


def get_project_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProjectService:
    return ProjectService(session)


ServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_ORG_CREATE],
)
async def create_project(
    organization_id: uuid.UUID, payload: ProjectCreateRequest, service: ServiceDep
) -> Project:
    return await service.create_project(
        organization_id=organization_id, name=payload.name, slug=payload.slug
    )


@router.get(
    "/organizations/{organization_id}/projects",
    response_model=ProjectListResponse,
    dependencies=[_ORG_READ],
)
async def list_projects(
    organization_id: uuid.UUID,
    service: ServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ProjectListResponse:
    result = await service.list_projects(organization_id, page=page, page_size=page_size)
    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse, dependencies=[_PROJECT_READ])
async def get_project(project_id: uuid.UUID, service: ServiceDep) -> Project:
    return await service.get_project(project_id)


@router.patch(
    "/projects/{project_id}", response_model=ProjectResponse, dependencies=[_PROJECT_UPDATE]
)
async def update_project(
    project_id: uuid.UUID, payload: ProjectUpdateRequest, service: ServiceDep
) -> Project:
    return await service.update_project(project_id, name=payload.name)
