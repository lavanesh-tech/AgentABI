"""Persistence access for AuditEvent (Security Phase E spec §15/§18).
Append + tenant-scoped list only — no update/delete method exists here,
matching the table's append-only posture (`app/models/audit_event.py`).
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.models.audit_event import AuditEvent


class AuditEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: AuditEvent) -> None:
        self._session.add(event)

    async def list_for_organization(
        self,
        organization_id: uuid.UUID,
        *,
        action: AuditAction | None = None,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[AuditEvent], int]:
        """Always tenant-scoped by `organization_id` (spec §18) — there
        is no "list all" variant, so a caller can never accidentally
        fetch another organization's audit trail by omitting a filter."""

        filters = [AuditEvent.organization_id == organization_id]
        if action is not None:
            filters.append(AuditEvent.action == action)

        count_stmt = select(func.count()).select_from(AuditEvent).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = (await self._session.execute(stmt)).scalars().all()
        return items, total
