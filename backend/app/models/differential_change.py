"""DifferentialChangeRecord — one persisted, immutable step-level
difference belonging to a `DifferentialReportRecord` (Phase 10).
Append-only, same posture as `ScanChange`/`ReplayStep`/`AuditEvent`: a
row is inserted once, already final; migration 0008 adds a database-
level trigger blocking UPDATE too (`DifferentialService` never offers
an update path in the first place).
"""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.differential_report import DifferentialReportRecord


class DifferentialChangeRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "differential_changes"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("differential_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deterministic display/storage position (spec §33) — mirrors
    # `ScanChange.order_index` (Phase 5): retrieval is `ORDER BY
    # order_index`, never a re-derived sort key.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    alignment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    # A step pair can carry more than one DifferenceType at once (e.g.
    # both STEP_STATUS_CHANGED and OUTPUT_CHANGED) — stored as a JSONB
    # array of the plain enum values, same "plain-text taxonomy" choice
    # ScanChange.change_type made in Phase 5 (docs/DECISIONS.md).
    difference_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    sequence_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    baseline_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("replay_steps.id", ondelete="SET NULL"), nullable=True
    )
    candidate_step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("replay_steps.id", ondelete="SET NULL"), nullable=True
    )
    baseline_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    candidate_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Already-sanitized (spec §12) before this row is ever built —
    # `DifferentialService` never persists a raw secret value here.
    output_differences: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    error_difference: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    latency_delta_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_percent_delta: Mapped[float | None] = mapped_column(Float, nullable=True)

    report: Mapped["DifferentialReportRecord"] = relationship(back_populates="changes")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"DifferentialChangeRecord(report_id={self.report_id!r}, "
            f"order_index={self.order_index!r}, alignment_method={self.alignment_method!r})"
        )
