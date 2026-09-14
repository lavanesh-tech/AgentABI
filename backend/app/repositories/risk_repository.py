"""Persistence access for `RiskAssessmentRecord`/`RiskRuleResultRecord`.
Thin, like every other repository — no scoring logic lives here; that's
`app/risk/engine.py`'s job, orchestrated by `RiskService`. Every read is
scoped by `project_id`, so a cross-project/cross-org id never resolves
(spec §26's tenant isolation) — same pattern as `DifferentialRepository`
(Phase 10).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.risk_assessment import RiskAssessmentRecord


class RiskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, assessment: RiskAssessmentRecord) -> None:
        self._session.add(assessment)

    async def get_by_id(
        self, project_id: uuid.UUID, assessment_id: uuid.UUID
    ) -> RiskAssessmentRecord | None:
        stmt = (
            select(RiskAssessmentRecord)
            .options(selectinload(RiskAssessmentRecord.rule_results))
            .where(
                RiskAssessmentRecord.id == assessment_id,
                RiskAssessmentRecord.project_id == project_id,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        project_id: uuid.UUID,
        compatibility_scan_id: uuid.UUID | None,
        differential_report_id: uuid.UUID | None,
        risk_engine_version: str,
    ) -> RiskAssessmentRecord | None:
        stmt = (
            select(RiskAssessmentRecord)
            .options(selectinload(RiskAssessmentRecord.rule_results))
            .where(
                RiskAssessmentRecord.project_id == project_id,
                RiskAssessmentRecord.compatibility_scan_id == compatibility_scan_id,
                RiskAssessmentRecord.differential_report_id == differential_report_id,
                RiskAssessmentRecord.risk_engine_version == risk_engine_version,
            )
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self, project_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[list[RiskAssessmentRecord], int]:
        count_stmt = (
            select(func.count())
            .select_from(RiskAssessmentRecord)
            .where(RiskAssessmentRecord.project_id == project_id)
        )
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(RiskAssessmentRecord)
            .where(RiskAssessmentRecord.project_id == project_id)
            .order_by(RiskAssessmentRecord.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total
