"""Persistence access for `DifferentialReportRecord`/
`DifferentialChangeRecord`. Thin, like every other repository — no
business rules live here; that's `DifferentialService`'s job. Every
read is scoped by `project_id`, so a cross-project/cross-org id never
resolves (spec §23's tenant isolation).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.differential_report import DifferentialReportRecord


class DifferentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, report: DifferentialReportRecord) -> None:
        self._session.add(report)

    async def get_by_id(
        self, project_id: uuid.UUID, report_id: uuid.UUID
    ) -> DifferentialReportRecord | None:
        stmt = (
            select(DifferentialReportRecord)
            .options(selectinload(DifferentialReportRecord.changes))
            .where(
                DifferentialReportRecord.id == report_id,
                DifferentialReportRecord.project_id == project_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        project_id: uuid.UUID,
        baseline_replay_id: uuid.UUID,
        candidate_replay_id: uuid.UUID,
        analyzer_version: str,
    ) -> DifferentialReportRecord | None:
        stmt = (
            select(DifferentialReportRecord)
            .options(selectinload(DifferentialReportRecord.changes))
            .where(
                DifferentialReportRecord.project_id == project_id,
                DifferentialReportRecord.baseline_replay_id == baseline_replay_id,
                DifferentialReportRecord.candidate_replay_id == candidate_replay_id,
                DifferentialReportRecord.analyzer_version == analyzer_version,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[list[DifferentialReportRecord], int]:
        count_stmt = (
            select(func.count())
            .select_from(DifferentialReportRecord)
            .where(DifferentialReportRecord.project_id == project_id)
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(DifferentialReportRecord)
            .where(DifferentialReportRecord.project_id == project_id)
            .order_by(DifferentialReportRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total
