"""github_identity: users.github_user_id, users.github_login

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("github_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("github_login", sa.String(length=255), nullable=True))
    # GitHub's numeric user id is the stable identity key (spec §8): a
    # unique constraint prevents two AgentABI users ever linking the
    # same GitHub account, and the index makes `get_by_github_id` a fast
    # lookup. Matches migration 0001's users.email pattern (separate
    # UniqueConstraint + index, both NULL-tolerant for now-nullable
    # columns since Postgres unique indexes allow multiple NULLs).
    op.create_unique_constraint("uq_users_github_user_id", "users", ["github_user_id"])
    op.create_index("ix_users_github_user_id", "users", ["github_user_id"])


def downgrade() -> None:
    op.drop_index("ix_users_github_user_id", table_name="users")
    op.drop_constraint("uq_users_github_user_id", "users", type_="unique")
    op.drop_column("users", "github_login")
    op.drop_column("users", "github_user_id")
