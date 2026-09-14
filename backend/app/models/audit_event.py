"""AuditEvent — append-only security/audit trail (Security Phase E spec
§12). Same immutability posture as `TrajectoryEvent`/`ReplayStep`
(Phase 6/7): a row is inserted exactly once and never updated —
`AuditService` offers no update method, and
`prevent_audit_event_mutation` (migration 0007) rejects any UPDATE or
DELETE at the database level too, unconditionally.

`organization_id`/`actor_user_id` use `ondelete="SET NULL"`, not the
`CASCADE` every tenant-scoped table elsewhere in this codebase uses —
deleting an organization or user must never silently delete the audit
trail that recorded what it did.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.actions import AuditAction
from app.models.base import Base, UUIDPrimaryKeyMixin


def _action_values(enum_cls: type[AuditAction]) -> list[str]:
    return [member.value for member in enum_cls]


class AuditEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action", values_callable=_action_values),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Allow-listed, redacted fields only (spec §14) — never an arbitrary
    # dump of the triggering request. Column named `metadata` in the
    # database, `audit_metadata` on the model (mirrors
    # `TrajectoryEvent.event_metadata`) since `metadata` is reserved by
    # SQLAlchemy's declarative `Base`.
    audit_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AuditEvent(id={self.id!r}, action={self.action!r})"
