"""Persistence access for `ReplayRun`/`ReplayStep`. Thin, like every
other repository in this codebase — tenant scoping and business rules
live in `ReplayService`; this module only knows how to read/write rows,
plus the one atomic status-transition statement.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.replay_run import ReplayRun
from app.models.replay_step import ReplayStep
from app.replay.models import ReplayStatus


class ReplayRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, replay_run: ReplayRun) -> None:
        self._session.add(replay_run)

    def add_step(self, step: ReplayStep) -> None:
        self._session.add(step)

    async def get_by_id(self, project_id: uuid.UUID, replay_id: uuid.UUID) -> ReplayRun | None:
        stmt = (
            select(ReplayRun)
            .options(selectinload(ReplayRun.steps))
            .where(ReplayRun.id == replay_id, ReplayRun.project_id == project_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_idempotency_key(
        self, project_id: uuid.UUID, idempotency_key: str
    ) -> ReplayRun | None:
        stmt = select(ReplayRun).where(
            ReplayRun.project_id == project_id, ReplayRun.idempotency_key == idempotency_key
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: ReplayStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[ReplayRun], int]:
        filters = [ReplayRun.project_id == project_id]
        if status is not None:
            filters.append(ReplayRun.status == status)

        count_stmt = select(func.count()).select_from(ReplayRun).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(ReplayRun)
            .where(*filters)
            .order_by(ReplayRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    async def list_steps(
        self, replay_run_id: uuid.UUID, *, offset: int, limit: int
    ) -> tuple[list[ReplayStep], int]:
        filters = [ReplayStep.replay_run_id == replay_run_id]
        count_stmt = select(func.count()).select_from(ReplayStep).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        # Ordering is always by `sequence_number` — mirrors Phase 6's
        # `TrajectoryRepository.list_events`, never reordered by
        # pagination (Phase 7 §5).
        stmt = (
            select(ReplayStep)
            .where(*filters)
            .order_by(ReplayStep.sequence_number)
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    async def transition_status(
        self,
        replay_id: uuid.UUID,
        *,
        from_status: ReplayStatus,
        to_status: ReplayStatus,
        error: str | None = None,
        started_at_now: bool = False,
        completed_at_now: bool = False,
    ) -> bool:
        """Atomic conditional `UPDATE ... WHERE status = :from_status`,
        the same TOCTOU-closing pattern as Phase 6's
        `TrajectoryRepository.transition_status` — two concurrent
        `execute_replay` calls for the same replay can never both
        observe PENDING and both proceed to RUNNING; only one `UPDATE`
        matches a row. Returns whether the transition actually applied.
        """

        values: dict[str, object] = {"status": to_status, "error": error}
        if started_at_now:
            values["started_at"] = func.now()
        if completed_at_now:
            values["completed_at"] = func.now()

        stmt = (
            update(ReplayRun)
            .where(ReplayRun.id == replay_id, ReplayRun.status == from_status)
            .values(**values)
        )
        result = await self._session.execute(stmt)
        return bool(result.rowcount)
