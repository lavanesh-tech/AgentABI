"""ScanChange — one structurally detected difference belonging to a
`CompatibilityScan`, mirroring `app/compatibility/models.py`'s `Change`
dataclass field-for-field (persistence has no logic of its own; the
engine already decided everything).

`change_type` is stored as plain text (indexed), not a Postgres native
enum, unlike `classification`/`severity`/`status` — see docs/DECISIONS.md
for why: the spec explicitly calls out that "later compatibility rules
will expand" the set of detectable change types, and a plain VARCHAR
means adding one is a Python-only change, not a migration.
"""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.compatibility.models import Classification, Severity
from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.compatibility_scan import CompatibilityScan


def _classification_values(enum_cls: type[Classification]) -> list[str]:
    return [member.value for member in enum_cls]


def _severity_values(enum_cls: type[Severity]) -> list[str]:
    return [member.value for member in enum_cls]


class ScanChange(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "scan_changes"

    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("compatibility_scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Deterministic display/storage position, computed once at scan time
    # from `diff.sort_changes()` (path, then change_type, then
    # classification) — see docs/DECISIONS.md's ordering ADR. Retrieval
    # just does `ORDER BY order_index`, rather than re-deriving the sort
    # key from stored columns on every read.
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)

    change_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    classification: Mapped[Classification] = mapped_column(
        Enum(
            Classification,
            name="compatibility_classification",
            values_callable=_classification_values,
        ),
        nullable=False,
    )
    severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="compatibility_severity", values_callable=_severity_values),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    scan: Mapped["CompatibilityScan"] = relationship(back_populates="changes")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ScanChange(scan_id={self.scan_id!r}, change_type={self.change_type!r}, "
            f"path={self.path!r})"
        )
