"""Audit event read API (Security Phase E spec §17/§18). OWNER/ADMIN
only (`Permission.AUDIT_READ`, `app/authz/permissions.py`) — MEMBER is
denied, same as every other privileged-read boundary in this codebase.
Always tenant-scoped by the `organization_id` path parameter via
`require_organization_permission`, mirroring
`require_project_permission`'s pattern for project-scoped routers
(`app/api/deps/authz.py`) — there is no "list all organizations'
events" variant.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.authz import require_organization_permission
from app.audit.actions import AuditAction
from app.authz.permissions import Permission
from app.core.database import get_db_session
from app.models.audit_event import AuditEvent
from app.services.audit_service import AuditService

router = APIRouter(prefix="/organizations/{organization_id}/audit-events", tags=["audit"])

_READ = Depends(require_organization_permission(Permission.AUDIT_READ))


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: AuditAction
    resource_type: str | None
    resource_id: str | None
    request_id: str | None
    correlation_id: str | None
    metadata: dict[str, Any] | None
    created_at: datetime

    @classmethod
    def from_event(cls, event: AuditEvent) -> "AuditEventResponse":
        return cls(
            id=event.id,
            organization_id=event.organization_id,
            actor_user_id=event.actor_user_id,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            metadata=event.audit_metadata,
            created_at=event.created_at,
        )


class AuditEventListResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int


@router.get(
    "",
    response_model=AuditEventListResponse,
    dependencies=[_READ],
    summary="List an organization's audit trail",
    description="Requires ADMIN or OWNER in the organization; MEMBER is denied. "
    "Always scoped to the organization_id in the path.",
)
async def list_audit_events(
    organization_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    action: Annotated[AuditAction | None, Query()] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> AuditEventListResponse:
    result = await AuditService(session).list_events(
        organization_id, action=action, page=page, page_size=page_size
    )
    return AuditEventListResponse(
        items=[AuditEventResponse.from_event(e) for e in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
    )
