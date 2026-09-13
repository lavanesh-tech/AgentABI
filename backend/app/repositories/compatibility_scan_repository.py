"""Persistence access for `CompatibilityScan`/`ScanChange`. Thin, like
every other repository in this codebase — no business rules (same-
component validation, tenant checks) live here; that's
`CompatibilityService`'s job. Every read is scoped by `project_id`.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.compatibility_scan import CompatibilityScan
from app.models.scan_change import ScanChange


class CompatibilityScanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, project_id: uuid.UUID, scan_id: uuid.UUID
    ) -> CompatibilityScan | None:
        stmt = (
            select(CompatibilityScan)
            .options(selectinload(CompatibilityScan.changes))
            .where(CompatibilityScan.id == scan_id, CompatibilityScan.project_id == project_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        component_id: uuid.UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CompatibilityScan], int]:
        filters = [CompatibilityScan.project_id == project_id]
        if component_id is not None:
            filters.append(CompatibilityScan.component_id == component_id)

        count_stmt = select(func.count()).select_from(CompatibilityScan).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(CompatibilityScan)
            .where(*filters)
            .order_by(CompatibilityScan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    def add(self, scan: CompatibilityScan) -> None:
        self._session.add(scan)

    def add_change(self, change: ScanChange) -> None:
        self._session.add(change)
