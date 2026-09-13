"""Component — the stable identity of a versioned system component
(agent, prompt, model, provider, MCP server, tool, schema, API, workflow,
or policy). Content/config lives on `ComponentVersion`; this row is what
later phases (Neo4j sync, compatibility scans, blast-radius) reference by
ID and never changes shape when a new version is registered.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.enums import ComponentStatus, ComponentType
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.component_version import ComponentVersion


def _enum_values(enum_cls: type[ComponentType] | type[ComponentStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class Component(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "components"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "component_type",
            "slug",
            name="uq_components_project_type_slug",
        ),
    )

    # Denormalized from project.organization_id (set once at creation by
    # the service layer, never changed) so tenant-scoped queries and the
    # future Neo4j sync don't need a join through projects just to filter
    # by organization.
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_type: Mapped[ComponentType] = mapped_column(
        Enum(ComponentType, name="component_type", values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Logical key, unique within (project_id, component_type) — see
    # docs/DECISIONS.md for why this isn't unique per-project across types.
    slug: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ComponentStatus] = mapped_column(
        Enum(ComponentStatus, name="component_status", values_callable=_enum_values),
        nullable=False,
        server_default=ComponentStatus.ACTIVE.value,
    )

    versions: Mapped[list["ComponentVersion"]] = relationship(
        back_populates="component",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ComponentVersion.sequence",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Component(id={self.id!r}, type={self.component_type!r}, slug={self.slug!r})"
