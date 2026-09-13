"""User — an account, global to the platform. Access to a given
organization/project is granted via `OrganizationMember`, not by any field
on this table, so a user can belong to multiple organizations."""

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"User(id={self.id!r}, email={self.email!r})"
