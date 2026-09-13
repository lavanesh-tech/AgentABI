"""Project — the unit later phases (component registry, dependency graph,
compatibility scans, GitHub repo bindings) attach to. Always scoped to
exactly one organization."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_projects_organization_id_slug"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Unique per-organization, not globally — two orgs may each have a
    # project named "payments".
    slug: Mapped[str] = mapped_column(String(100), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="projects")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Project(id={self.id!r}, slug={self.slug!r})"
