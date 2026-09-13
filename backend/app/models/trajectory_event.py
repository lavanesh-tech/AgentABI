"""TrajectoryEvent — one immutable, ordered step of a recorded trajectory.

Append-only historical evidence, same posture as Phase 5's `ScanChange`:
no service method ever updates a row after insert, and
`prevent_trajectory_event_mutation` (migration 0004) rejects any UPDATE
at the database level too, unconditionally — there is no legitimately
mutable field on this table once an event is recorded.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.trajectory.models import EventType

if TYPE_CHECKING:
    from app.models.trajectory import Trajectory


def _event_type_values(enum_cls: type[EventType]) -> list[str]:
    return [member.value for member in enum_cls]


class TrajectoryEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "trajectory_events"

    trajectory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trajectories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Concurrency-safe, trajectory-local monotonic order — allocated by
    # `TrajectoryRepository.allocate_sequence` (an atomic
    # `next_sequence += 1 RETURNING`), never by reading `max(sequence)`
    # and incrementing in application code. Unique per trajectory
    # (migration 0004) as a database-level backstop.
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)

    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="trajectory_event_type", values_callable=_event_type_values),
        nullable=False,
        index=True,
    )

    # When the event actually happened vs. when this row was written —
    # can differ for evidence that arrives slightly delayed (Phase 6
    # §24). Ordering always relies on `sequence_number`, never on either
    # timestamp.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # The exact immutable component version active when this event
    # occurred (Phase 6 §6) — not just the mutable logical component.
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=True, index=True
    )
    component_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("trajectory_events.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Idempotency key for ingestion retries (Phase 6 §14) — unique per
    # trajectory when set (migration 0004's partial unique index).
    external_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    input: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    event_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Payload-size safeguard bookkeeping (Phase 6 §10) — set when any of
    # input/output/error/metadata had to be stored as a truncated
    # representation instead of in full.
    payload_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_original_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # SHA-256 integrity/replay-evidence hash over the replay-relevant
    # fields (Phase 6 §18) — see `app/trajectory/hashing.py`.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    trajectory: Mapped["Trajectory"] = relationship(back_populates="events")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"TrajectoryEvent(trajectory_id={self.trajectory_id!r}, "
            f"sequence_number={self.sequence_number!r}, event_type={self.event_type!r})"
        )
