"""DifferentialReportRecord — a persisted, immutable-once-created record
of one deterministic differential analysis run (`app/differential/`)
comparing a baseline `ReplayRun`'s steps against a candidate `ReplayRun`'s
steps (Phase 10).

Named `...Record` (not `DifferentialReport`) to avoid colliding with the
pure `app.differential.models.DifferentialReport` dataclass — same
naming split as `Change` (pure) vs `ScanChange` (persisted), Phase 5.

This row is evidence, not a live view: summary counts are a snapshot of
what the analyzer concluded when it ran (spec §17) — a re-run always
creates a new report row (guarded by the idempotency unique constraint
in migration 0008), never updates or reuses an old one.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.differential_change import DifferentialChangeRecord


class DifferentialReportRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "differential_reports"
    __table_args__ = (
        # Idempotency key (spec §19): the same logical comparison, run
        # again with the same analyzer version, never creates a second
        # report — `DifferentialRepository.get_by_idempotency_key` is
        # checked before insert.
        UniqueConstraint(
            "project_id",
            "baseline_replay_id",
            "candidate_replay_id",
            "analyzer_version",
            name="uq_differential_reports_idempotency",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    baseline_replay_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("replay_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_replay_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("replay_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional cross-reference to a relevant Phase 5 compatibility scan
    # (spec §16) — never required, never enforced beyond same-project.
    compatibility_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compatibility_scans.id", ondelete="SET NULL"), nullable=True
    )

    # Deterministic ruleset version (spec §20) — never bumped in place;
    # a comparison-rule change ships as a new version so old reports
    # never silently change meaning.
    analyzer_version: Mapped[str] = mapped_column(String(20), nullable=False)

    total_baseline_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    total_candidate_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    added_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    removed_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    new_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    resolved_failures: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_outputs: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_changes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Canonical SHA-256 over the report's deterministic content (spec
    # §34) — supports reproducibility checks; not used for lookup.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    changes: Mapped[list["DifferentialChangeRecord"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DifferentialChangeRecord.order_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DifferentialReportRecord(id={self.id!r}, project_id={self.project_id!r}, "
            f"baseline_replay_id={self.baseline_replay_id!r}, "
            f"candidate_replay_id={self.candidate_replay_id!r})"
        )
