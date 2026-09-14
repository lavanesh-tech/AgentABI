"""RiskRuleResultRecord — one persisted, immutable triggered-rule
result belonging to a `RiskAssessmentRecord` (Phase 11). Append-only,
same posture as `DifferentialChangeRecord`/`ScanChange`: a row is
inserted once, already final; migration 0009 adds a database-level
trigger blocking UPDATE too.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.risk_assessment import RiskAssessmentRecord


class RiskRuleResultRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "risk_rule_results"

    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("risk_assessments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deterministic display/storage position (spec §21) — mirrors
    # `DifferentialChangeRecord.order_index`.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    rule_id: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    score_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    hard_block: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    assessment: Mapped["RiskAssessmentRecord"] = relationship(back_populates="rule_results")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"RiskRuleResultRecord(assessment_id={self.assessment_id!r}, rule_id={self.rule_id!r})"
        )
