"""ComponentVersion — an immutable snapshot of a component's content at a
point in time. New changes always create a new row; existing rows are
never semantically mutated. That's enforced two ways: the service layer
exposes no "update version" method at all, and a database trigger
(`prevent_component_version_mutation`, created in
`alembic/versions/0002_component_registry.py`) rejects any UPDATE that
would change `content` or `checksum`, so mutation is blocked even for a
write that bypasses the ORM entirely.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.component import Component


class ComponentVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "component_versions"
    __table_args__ = (
        UniqueConstraint(
            "component_id", "version", name="uq_component_versions_component_id_version"
        ),
    )

    component_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("components.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Free-form version identifier ("1", "v18", "2.1.0", ...) — see
    # docs/DECISIONS.md for why this isn't a parsed semver type.
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    # Global monotonic ordering surrogate (a Postgres IDENTITY column) used
    # to find "the latest version of a component" with a simple indexed
    # ORDER BY, instead of created_at — which two versions inserted in the
    # same millisecond could tie on.
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False, unique=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Mapped attribute can't be named `metadata` — that name is reserved by
    # SQLAlchemy's DeclarativeBase (`Base.metadata`) — so the Python
    # attribute is `version_metadata` while the actual column stays named
    # `metadata` in the database.
    version_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    # Deliberately no TimestampMixin/updated_at here: this row is
    # immutable, so it never has a meaningful "updated at".
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    component: Mapped["Component"] = relationship(back_populates="versions")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ComponentVersion(component_id={self.component_id!r}, version={self.version!r})"
