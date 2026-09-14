"""GitHub PR integration: github_repository_mappings, github_pr_analyses

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_repository_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("github_repository_full_name", sa.String(length=255), nullable=False),
        sa.Column("github_installation_id", sa.BigInteger(), nullable=True),
        sa.Column("baseline_version", sa.String(length=50), nullable=True),
        sa.UniqueConstraint("github_repository_id", name="uq_github_repository_mappings_repo_id"),
    )
    op.create_index(
        "ix_github_repository_mappings_organization_id",
        "github_repository_mappings",
        ["organization_id"],
    )
    op.create_index(
        "ix_github_repository_mappings_project_id", "github_repository_mappings", ["project_id"]
    )
    op.create_index(
        "ix_github_repository_mappings_github_repository_id",
        "github_repository_mappings",
        ["github_repository_id"],
    )

    op.create_table(
        "github_pr_analyses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("github_repository_id", sa.BigInteger(), nullable=False),
        sa.Column("pull_request_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(length=40), nullable=False),
        sa.Column("base_sha", sa.String(length=40), nullable=False),
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("analysis_version", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("decision", sa.String(length=10), nullable=True),
        sa.Column(
            "compatibility_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compatibility_scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "risk_assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("risk_assessments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_run_id", sa.BigInteger(), nullable=True),
        sa.Column("publish_error", sa.String(length=500), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint(
            "github_repository_id",
            "pull_request_number",
            "head_sha",
            "analysis_version",
            name="uq_github_pr_analyses_idempotency",
        ),
    )
    op.create_index(
        "ix_github_pr_analyses_organization_id", "github_pr_analyses", ["organization_id"]
    )
    op.create_index("ix_github_pr_analyses_project_id", "github_pr_analyses", ["project_id"])
    op.create_index(
        "ix_github_pr_analyses_github_repository_id", "github_pr_analyses", ["github_repository_id"]
    )
    op.create_index("ix_github_pr_analyses_head_sha", "github_pr_analyses", ["head_sha"])

    # `status` uses a Postgres native enum type via the ORM's
    # `Enum(..., values_callable=...)` — created implicitly by
    # SQLAlchemy on first use in application code paths that create
    # rows through the ORM is NOT how Alembic works: the enum type must
    # exist before the column can be typed with it. Since the column
    # above is created as a plain VARCHAR with a string server_default
    # (not a Postgres ENUM type) this migration intentionally mirrors
    # `scan_changes.change_type`'s "plain text, not a native enum"
    # choice (see docs/DECISIONS.md) for this one column — the ORM's
    # `Enum(...)` mapped type still validates values in Python, it is
    # simply backed by VARCHAR at the database level here, avoiding an
    # extra `CREATE TYPE`/`ALTER TYPE` migration step for a status
    # column expected to grow new values over time.


def downgrade() -> None:
    op.drop_table("github_pr_analyses")
    op.drop_table("github_repository_mappings")
