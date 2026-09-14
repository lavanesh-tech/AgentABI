"""ReplayRun — one controlled replay of a historical trajectory against a
candidate component-version substitution.

Same mutability posture as `Trajectory` (Phase 6 ADR-027): starts
PENDING and is updated by the service layer exactly through its status
transitions (`started_at`/`completed_at`/`error`/`status`) — no database
trigger, protected only by `ReplayService` never offering any other
mutation path. `plan` is set once at creation and never touched again in
practice, even though nothing enforces that at the database level (it
would need its own table to get a real immutability guarantee, which
`replay_steps` provides for the plan's actual execution evidence).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.replay.models import ReplayStatus

if TYPE_CHECKING:
    from app.models.replay_step import ReplayStep


def _status_values(enum_cls: type[ReplayStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class ReplayRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "replay_runs"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_trajectory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("trajectories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # The logical component being substituted (baseline/candidate versions
    # both belong to it — validated at creation).
    component_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_component_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_component_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[ReplayStatus] = mapped_column(
        Enum(ReplayStatus, name="replay_status", values_callable=_status_values),
        nullable=False,
        default=ReplayStatus.PENDING,
    )

    # Idempotency key for create-replay retries (Phase 7 §12), unique per
    # project when set — same pattern as `Trajectory.external_run_id`
    # (Phase 6 ADR-029).
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # The deterministic plan built by `app/replay/planner.py` at creation
    # time, serialized once and never recomputed — `execute_replay`
    # replays exactly this plan, so a replay's evidence is reproducible
    # even if candidate/baseline data were hypothetically to change later.
    plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    steps: Mapped[list["ReplayStep"]] = relationship(
        back_populates="replay_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ReplayStep.sequence_number",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ReplayRun(id={self.id!r}, project_id={self.project_id!r}, status={self.status!r})"
