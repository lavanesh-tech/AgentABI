"""Trajectory — the record of one historical agent-execution run.

Unlike `CompatibilityScan` (Phase 5), a trajectory is *not* immutable
end-to-end: it starts `RUNNING` and is deliberately updated exactly
twice more by the service layer — once to allocate each event's
`next_sequence`, and once to transition to a terminal status
(`completed_at`/`error` set alongside `status`). No database trigger
blocks this, unlike `component_versions`/`compatibility_scans`/
`scan_changes` — the identity/config fields (`project_id`,
`external_run_id`, `workflow_version_id`, ...) simply have no service
method that ever touches them after `start_trajectory`, the same
"protected by never offering a mutation path" discipline Phase 3 uses
for `components` (whose *identity* row also has no immutability
trigger, only `component_versions` does). See docs/DECISIONS.md.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.trajectory.models import TrajectoryStatus

if TYPE_CHECKING:
    from app.models.trajectory_event import TrajectoryEvent


def _status_values(enum_cls: type[TrajectoryStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class Trajectory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trajectories"

    # Denormalized for direct project-scoped queries, same convention as
    # `components`/`compatibility_scans`.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The workflow (or agent) component version this run executed under,
    # where a Workflow/Agent component actually models the run — nullable
    # because not every trajectory originates from a registered Workflow
    # component (Phase 6 §7). The *initiating agent's* version is instead
    # captured by that run's own AGENT_STARTED event, avoiding a second
    # place to keep it in sync.
    workflow_component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=True, index=True
    )
    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=True
    )

    # Idempotency key for the originating external instrumentation retrying
    # its own "start" call (Phase 6 §13) — unique per project when set (see
    # migration 0004's partial unique index), never globally unique (two
    # different projects legitimately using the same run-id scheme should
    # not collide).
    external_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[TrajectoryStatus] = mapped_column(
        Enum(TrajectoryStatus, name="trajectory_status", values_callable=_status_values),
        nullable=False,
        default=TrajectoryStatus.RUNNING,
    )

    environment: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Observability-preparation fields (Phase 6 §30) — usable today as
    # opaque correlation strings without requiring OpenTelemetry (Phase
    # 15) to exist yet.
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    span_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tags: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Catch-all for execution-context data that doesn't warrant its own
    # column (e.g. a future "baseline_config_id" — Phase 6 §7) — mapped
    # attribute can't be named `metadata`, same reason as
    # `ComponentVersion.version_metadata`.
    trajectory_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )

    # Atomically incremented by `TrajectoryRepository.allocate_sequence`
    # (a single `UPDATE ... SET next_sequence = next_sequence + 1
    # RETURNING next_sequence`) — the concurrency-safe sequence source for
    # this trajectory's events. See docs/DECISIONS.md.
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # `duration` is deliberately not a stored column: it is always
    # `completed_at - started_at`, computed by the API response layer
    # (`app/api/v1/trajectories.py`) rather than duplicated at write time
    # and risking the two disagreeing.

    events: Mapped[list["TrajectoryEvent"]] = relationship(
        back_populates="trajectory",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="TrajectoryEvent.sequence_number",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Trajectory(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})"
