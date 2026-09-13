"""OrganizationMember — the association between a User and an
Organization, carrying the user's role within that organization.

This is the minimal support table needed for correct org-level isolation
now. Full RBAC (permission checks, project-level roles, API enforcement)
is a later phase; this table only establishes the data model so that later
phase's authorization logic has something to query.
"""

import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class OrganizationRole(enum.StrEnum):
    """Coarse-grained role within an organization. Kept intentionally small
    (owner/admin/member) — fine-grained/project-level permissions are a
    later-phase concern (see docs/PROJECT_SPEC.md §20 Security)."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class OrganizationMember(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_members_org_user"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[OrganizationRole] = mapped_column(
        Enum(
            OrganizationRole,
            name="organization_role",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        server_default=OrganizationRole.MEMBER.value,
    )

    organization: Mapped["Organization"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"OrganizationMember(organization_id={self.organization_id!r}, "
            f"user_id={self.user_id!r}, role={self.role!r})"
        )
