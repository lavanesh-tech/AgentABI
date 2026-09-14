"""Component Registry API — create/list/get components and their
immutable versions, scoped to a project.

Routes never touch the ORM or repositories directly; all business rules
(duplicate detection, tenant scoping, content validation, checksum
computation) live in `ComponentRegistryService`. Domain exceptions raised
by the service are translated to HTTP responses centrally in
`app/api/v1/errors.py` — no try/except here.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_project_permission
from app.authz.permissions import Permission
from app.core.database import get_db_session
from app.domain.enums import ComponentStatus, ComponentType
from app.models.component import Component
from app.models.component_version import ComponentVersion
from app.services.component_registry import ComponentRegistryService

router = APIRouter(prefix="/projects/{project_id}/components", tags=["components"])

_READ = Depends(require_project_permission(Permission.COMPONENT_READ))
_WRITE = Depends(require_project_permission(Permission.COMPONENT_WRITE))

_SLUG_PATTERN = r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"


class PageResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class ComponentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_type: ComponentType
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=150, pattern=_SLUG_PATTERN)
    description: str | None = None


class ComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    organization_id: uuid.UUID
    component_type: ComponentType
    name: str
    slug: str
    description: str | None
    status: ComponentStatus
    created_at: datetime
    updated_at: datetime


class ComponentVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=50)
    content: dict[str, Any]
    version_metadata: dict[str, Any] | None = None


class ComponentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    component_id: uuid.UUID
    version: str
    sequence: int
    content: dict[str, Any]
    checksum: str
    version_metadata: dict[str, Any] | None
    created_at: datetime


def get_registry_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ComponentRegistryService:
    return ComponentRegistryService(session)


ServiceDep = Annotated[ComponentRegistryService, Depends(get_registry_service)]


@router.post(
    "",
    response_model=ComponentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_component(
    project_id: uuid.UUID, payload: ComponentCreateRequest, service: ServiceDep
) -> Component:
    return await service.create_component(
        project_id=project_id,
        component_type=payload.component_type,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
    )


@router.get("", response_model=PageResponse[ComponentResponse], dependencies=[_READ])
async def list_components(
    project_id: uuid.UUID,
    service: ServiceDep,
    component_type: ComponentType | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse[ComponentResponse]:
    result = await service.list_components(
        project_id, component_type=component_type, page=page, page_size=page_size
    )
    return PageResponse(
        items=[ComponentResponse.model_validate(c) for c in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


@router.get("/{component_id}", response_model=ComponentResponse, dependencies=[_READ])
async def get_component(
    project_id: uuid.UUID, component_id: uuid.UUID, service: ServiceDep
) -> Component:
    return await service.get_component(project_id, component_id)


@router.post(
    "/{component_id}/versions",
    response_model=ComponentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_component_version(
    project_id: uuid.UUID,
    component_id: uuid.UUID,
    payload: ComponentVersionCreateRequest,
    service: ServiceDep,
) -> ComponentVersion:
    return await service.create_component_version(
        project_id=project_id,
        component_id=component_id,
        version=payload.version,
        content=payload.content,
        version_metadata=payload.version_metadata,
    )


@router.get(
    "/{component_id}/versions",
    response_model=PageResponse[ComponentVersionResponse],
    dependencies=[_READ],
)
async def list_component_versions(
    project_id: uuid.UUID,
    component_id: uuid.UUID,
    service: ServiceDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PageResponse[ComponentVersionResponse]:
    result = await service.list_component_versions(
        project_id, component_id, page=page, page_size=page_size
    )
    return PageResponse(
        items=[ComponentVersionResponse.model_validate(v) for v in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )


# Registered before the "/{version}" route below so a literal request for
# "/versions/latest" is never swallowed by the "{version}" path parameter.
@router.get(
    "/{component_id}/versions/latest",
    response_model=ComponentVersionResponse,
    dependencies=[_READ],
)
async def get_latest_component_version(
    project_id: uuid.UUID, component_id: uuid.UUID, service: ServiceDep
) -> ComponentVersion:
    return await service.get_latest_component_version(project_id, component_id)


@router.get(
    "/{component_id}/versions/{version}",
    response_model=ComponentVersionResponse,
    dependencies=[_READ],
)
async def get_component_version(
    project_id: uuid.UUID, component_id: uuid.UUID, version: str, service: ServiceDep
) -> ComponentVersion:
    return await service.get_component_version(project_id, component_id, version)
