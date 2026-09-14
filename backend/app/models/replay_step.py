"""ReplayStep — one immutable, ordered piece of replay evidence.

Append-only, same posture as `TrajectoryEvent` (Phase 6): a row is
inserted exactly once, already in its final `status` — `ReplayService`
never updates a `ReplayStep` after insert, and
`prevent_replay_step_mutation` (migration 0005) rejects any UPDATE at
the database level too, unconditionally.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.replay.models import StepKind, StepStatus

if TYPE_CHECKING:
    from app.models.replay_run import ReplayRun


def _kind_values(enum_cls: type[StepKind]) -> list[str]:
    return [member.value for member in enum_cls]


def _status_values(enum_cls: type[StepStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class ReplayStep(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "replay_steps"

    replay_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("replay_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Mirrors the source event's own `sequence_number` — replay evidence
    # preserves Phase 6 trajectory ordering exactly, never re-deriving
    # order from timestamps or insertion order (Phase 7 §5).
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trajectory_events.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[StepKind] = mapped_column(
        Enum(StepKind, name="replay_step_kind", values_callable=_kind_values), nullable=False
    )
    status: Mapped[StepStatus] = mapped_column(
        Enum(StepStatus, name="replay_step_status", values_callable=_status_values),
        nullable=False,
    )

    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # The version actually used for this step: the candidate for a
    # substituted step, the historical version for a reused one, `None`
    # for provider-required/skipped steps.
    component_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    input: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    replay_run: Mapped["ReplayRun"] = relationship(back_populates="steps")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ReplayStep(replay_run_id={self.replay_run_id!r}, "
            f"sequence_number={self.sequence_number!r}, kind={self.kind!r}, status={self.status!r})"
        )
