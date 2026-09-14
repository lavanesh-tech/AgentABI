"""AuditService — the single place an audit event is appended (Security
Phase E spec §15). Not GitHub-specific: any future security/product
code records through this same service rather than re-deriving
redaction/metadata-safety logic.

`record()` only adds the event to the session — it deliberately does
not flush/commit, so callers can batch it into the same transaction as
the business operation being audited (mirrors every other service in
this codebase, e.g. `TrajectoryRecorderService.start_trajectory`).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.models.audit_event import AuditEvent
from app.repositories.audit_event_repository import AuditEventRepository
from app.trajectory.redaction import sanitize


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._events = AuditEventRepository(session)

    def record(
        self,
        *,
        action: AuditAction,
        organization_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: Any = None,
        request_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        """Appends one audit event. `metadata` is redacted via the same
        `sanitize()` every trajectory event payload goes through (spec
        §14/§16) — callers should still allow-list what they pass rather
        than relying on redaction alone (spec §14: "prefer allow-listed
        metadata rather than dumping arbitrary request structures")."""

        event = AuditEvent(
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=request_id,
            correlation_id=correlation_id,
            audit_metadata=sanitize(metadata) if metadata else None,
        )
        self._events.add(event)
        return event

    async def list_events(
        self,
        organization_id: uuid.UUID,
        *,
        action: AuditAction | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[AuditEvent]:
        offset = (page - 1) * page_size
        items, total = await self._events.list_for_organization(
            organization_id, action=action, offset=offset, limit=page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)
