"""CompatibilityScan — a persisted, immutable-once-created record of one
run of the deterministic compatibility engine (`app/compatibility/`)
comparing a baseline `ComponentVersion` against a candidate
`ComponentVersion` of the same `Component`.

This row is evidence, not a live view: `summary_*`/`severity_*` counts
and `status` are a snapshot of what the engine concluded when the scan
ran, not something recomputed on read. See docs/DECISIONS.md for why
re-running the same comparison always creates a new scan row rather than
updating or reusing an old one.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.compatibility.models import CompatibilityStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.scan_change import ScanChange


def _status_values(enum_cls: type[CompatibilityStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class CompatibilityScan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "compatibility_scans"

    # Denormalized, like `components.organization_id` (Phase 3) and
    # `Component` nodes' `project_id` (Phase 4): every scan is scoped and
    # queried by project directly, without a join through `components`.
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("component_versions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[CompatibilityStatus] = mapped_column(
        Enum(CompatibilityStatus, name="compatibility_status", values_callable=_status_values),
        nullable=False,
    )

    total_changes: Mapped[int] = mapped_column(Integer, nullable=False)
    compatible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    potentially_breaking_count: Mapped[int] = mapped_column(Integer, nullable=False)
    breaking_count: Mapped[int] = mapped_column(Integer, nullable=False)

    severity_info_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_low_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_medium_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_high_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    severity_critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # `created_at` from TimestampMixin is this row's "scanned at" — no
    # `updated_at`-driven mutation is ever meaningful for a point-in-time
    # evidence snapshot, so TimestampMixin's `updated_at` column exists
    # but is deliberately never written to after insert (also enforced by
    # the immutability trigger — see migration 0003).

    changes: Mapped[list["ScanChange"]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScanChange.order_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CompatibilityScan(id={self.id!r}, component_id={self.component_id!r}, "
            f"status={self.status!r})"
        )
