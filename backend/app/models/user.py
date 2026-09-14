"""User — an account, global to the platform. Access to a given
organization/project is granted via `OrganizationMember`, not by any field
on this table, so a user can belong to multiple organizations.

`github_user_id` (Security Phase B) is GitHub's immutable numeric user
id — the stable identity key for GitHub OAuth login, never the
`github_login` username, which GitHub allows a user to change at any
time. Nullable: a user created some other way (none exist yet — Phase A
shipped no signup path) simply has no linked GitHub identity."""

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    github_user_id: Mapped[int | None] = mapped_column(
        BigInteger, unique=True, index=True, nullable=True
    )
    github_login: Mapped[str | None] = mapped_column(String(255), nullable=True)

    memberships: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"User(id={self.id!r}, email={self.email!r})"
