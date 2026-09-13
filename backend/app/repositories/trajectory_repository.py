"""Persistence access for `Trajectory`/`TrajectoryEvent`. Thin, like every
other repository in this codebase — tenant scoping and business rules
(idempotency, transition validity, event validation) live in
`TrajectoryRecorderService`; this module only knows how to read/write
rows, plus the one piece of SQL that must be atomic: sequence
allocation.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.trajectory import Trajectory
from app.models.trajectory_event import TrajectoryEvent
from app.trajectory.models import EventType, TrajectoryStatus


class TrajectoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, trajectory: Trajectory) -> None:
        self._session.add(trajectory)

    def add_event(self, event: TrajectoryEvent) -> None:
        self._session.add(event)

    async def get_by_id(self, project_id: uuid.UUID, trajectory_id: uuid.UUID) -> Trajectory | None:
        stmt = (
            select(Trajectory)
            .options(selectinload(Trajectory.events))
            .where(Trajectory.id == trajectory_id, Trajectory.project_id == project_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_external_run_id(
        self, project_id: uuid.UUID, external_run_id: str
    ) -> Trajectory | None:
        stmt = select(Trajectory).where(
            Trajectory.project_id == project_id, Trajectory.external_run_id == external_run_id
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: uuid.UUID,
        *,
        status: TrajectoryStatus | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Trajectory], int]:
        filters = [Trajectory.project_id == project_id]
        if status is not None:
            filters.append(Trajectory.status == status)

        count_stmt = select(func.count()).select_from(Trajectory).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        stmt = (
            select(Trajectory)
            .where(*filters)
            .order_by(Trajectory.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    async def list_events(
        self,
        trajectory_id: uuid.UUID,
        *,
        event_type: EventType | None,
        offset: int,
        limit: int,
    ) -> tuple[list[TrajectoryEvent], int]:
        filters = [TrajectoryEvent.trajectory_id == trajectory_id]
        if event_type is not None:
            filters.append(TrajectoryEvent.event_type == event_type)

        count_stmt = select(func.count()).select_from(TrajectoryEvent).where(*filters)
        total = (await self._session.execute(count_stmt)).scalar_one()

        # Ordering is always by `sequence_number` — never `occurred_at`/
        # `recorded_at`/insertion order — and pagination never reorders
        # it: `OFFSET`/`LIMIT` on top of a single deterministic `ORDER BY`
        # simply slices the same total order (Phase 6 §20).
        stmt = (
            select(TrajectoryEvent)
            .where(*filters)
            .order_by(TrajectoryEvent.sequence_number)
            .offset(offset)
            .limit(limit)
        )
        items = list((await self._session.execute(stmt)).scalars().all())
        return items, total

    async def get_event_by_external_id(
        self, trajectory_id: uuid.UUID, external_event_id: str
    ) -> TrajectoryEvent | None:
        stmt = select(TrajectoryEvent).where(
            TrajectoryEvent.trajectory_id == trajectory_id,
            TrajectoryEvent.external_event_id == external_event_id,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def allocate_sequence(self, trajectory_id: uuid.UUID) -> int | None:
        """Atomically allocate the next `sequence_number` for this
        trajectory, in a single `UPDATE ... RETURNING` — never a
        `SELECT max(sequence_number) + 1` followed by a separate insert,
        which two concurrent appenders could both read before either
        writes (Phase 6 §15). Postgres serializes concurrent UPDATEs to
        the same row, so each concurrent caller is guaranteed a distinct,
        gapless increment.

        The `WHERE status = RUNNING` clause folds the terminal-status
        check into the same atomic statement, closing the race between
        "check the trajectory is still RUNNING" and "allocate a
        sequence number" that two separate statements would leave open.
        Returns `None` if the trajectory doesn't exist or isn't RUNNING —
        the caller (already holding a loaded `Trajectory`) distinguishes
        those cases itself.
        """

        stmt = (
            update(Trajectory)
            .where(Trajectory.id == trajectory_id, Trajectory.status == TrajectoryStatus.RUNNING)
            .values(next_sequence=Trajectory.next_sequence + 1)
            .returning(Trajectory.next_sequence)
        )
        result = await self._session.execute(stmt)
        row = result.first()
        return None if row is None else row[0]

    async def transition_status(
        self,
        trajectory_id: uuid.UUID,
        *,
        from_status: TrajectoryStatus,
        to_status: TrajectoryStatus,
        error: str | None,
    ) -> bool:
        """Atomically transition status, conditioned on the trajectory
        still being in `from_status` — same TOCTOU-closing pattern as
        `allocate_sequence`. Returns whether the row was actually
        updated (False means it was no longer `from_status`)."""

        stmt = (
            update(Trajectory)
            .where(Trajectory.id == trajectory_id, Trajectory.status == from_status)
            .values(status=to_status, completed_at=func.now(), error=error)
            .returning(Trajectory.id)
        )
        result = await self._session.execute(stmt)
        return result.first() is not None
