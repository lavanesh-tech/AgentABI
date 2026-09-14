"""RiskAssessmentRecord — a persisted, immutable-once-created record of
one deterministic risk evaluation (`app/risk/engine.py`) over a
compatibility scan and/or a differential report (Phase 11).

Named `...Record` (not `RiskAssessment`) to avoid colliding with the
pure `app.risk.models.RiskAssessment` dataclass — same naming split as
`DifferentialReportRecord` vs `app.differential.models.DifferentialReport`
(Phase 10).
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.risk_rule_result import RiskRuleResultRecord


class RiskAssessmentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        # Idempotency key (spec §23): re-running the risk engine at the
        # same version against the same (scan, report) pair returns the
        # existing assessment rather than creating a duplicate — same
        # posture as `differential_reports`' unique constraint (Phase 10).
        UniqueConstraint(
            "project_id",
            "compatibility_scan_id",
            "differential_report_id",
            "risk_engine_version",
            name="uq_risk_assessments_idempotency",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Both nullable and independently optional (spec §4/§23): a risk
    # assessment can be run from a compatibility scan alone, a
    # differential report alone, or both together.
    compatibility_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compatibility_scans.id", ondelete="SET NULL"), nullable=True, index=True
    )
    differential_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("differential_reports.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Versioned ruleset identifier (spec §19) — never bumped in place;
    # a rule-set change ships as a new version so old assessments never
    # silently change meaning.
    risk_engine_version: Mapped[str] = mapped_column(String(20), nullable=False)

    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    hard_block: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Canonical SHA-256 over the assessment's deterministic content —
    # supports reproducibility checks, same pattern as
    # `DifferentialReportRecord.content_hash` (Phase 10).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    rule_results: Mapped[list["RiskRuleResultRecord"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RiskRuleResultRecord.order_index",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RiskAssessmentRecord(id={self.id!r}, project_id={self.project_id!r}, "
            f"decision={self.decision!r}, score={self.score!r})"
        )
