"""differential reports: differential_reports, differential_changes

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# differential_reports/differential_changes are derived, immutable
# evidence (Phase 10 spec §17) — same pattern as migration 0005's
# `prevent_replay_step_mutation`: the service layer offers no update
# path, and this is the database-level backstop. UPDATE only (not
# DELETE) — mirrors replay_steps, not audit_events, since there's no
# security requirement here that a report survive an intentional
# project/replay cascade delete.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_differential_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        '% are immutable once created (id=%)', TG_TABLE_NAME, OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_REPORT_TRIGGER = """
CREATE TRIGGER trg_differential_reports_immutable
BEFORE UPDATE ON differential_reports
FOR EACH ROW
EXECUTE FUNCTION prevent_differential_mutation();
"""

_CHANGE_TRIGGER = """
CREATE TRIGGER trg_differential_changes_immutable
BEFORE UPDATE ON differential_changes
FOR EACH ROW
EXECUTE FUNCTION prevent_differential_mutation();
"""


def upgrade() -> None:
    op.create_table(
        "differential_reports",
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
            "baseline_replay_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_replay_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "compatibility_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compatibility_scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("analyzer_version", sa.String(length=20), nullable=False),
        sa.Column("total_baseline_steps", sa.Integer(), nullable=False),
        sa.Column("total_candidate_steps", sa.Integer(), nullable=False),
        sa.Column("matched_steps", sa.Integer(), nullable=False),
        sa.Column("added_steps", sa.Integer(), nullable=False),
        sa.Column("removed_steps", sa.Integer(), nullable=False),
        sa.Column("changed_steps", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("resolved_failures", sa.Integer(), nullable=False),
        sa.Column("changed_outputs", sa.Integer(), nullable=False),
        sa.Column("schema_changes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "baseline_replay_id",
            "candidate_replay_id",
            "analyzer_version",
            name="uq_differential_reports_idempotency",
        ),
    )
    op.create_index(
        "ix_differential_reports_organization_id", "differential_reports", ["organization_id"]
    )
    op.create_index("ix_differential_reports_project_id", "differential_reports", ["project_id"])
    op.create_index(
        "ix_differential_reports_baseline_replay_id",
        "differential_reports",
        ["baseline_replay_id"],
    )
    op.create_index(
        "ix_differential_reports_candidate_replay_id",
        "differential_reports",
        ["candidate_replay_id"],
    )

    op.create_table(
        "differential_changes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("differential_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("alignment_method", sa.String(length=30), nullable=False),
        sa.Column("difference_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=True),
        sa.Column(
            "baseline_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "candidate_step_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_steps.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("baseline_status", sa.String(length=30), nullable=True),
        sa.Column("candidate_status", sa.String(length=30), nullable=True),
        sa.Column("output_differences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_difference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latency_delta_ms", sa.Integer(), nullable=True),
        sa.Column("latency_percent_delta", sa.Float(), nullable=True),
    )
    op.create_index("ix_differential_changes_report_id", "differential_changes", ["report_id"])
    op.create_index(
        "ix_differential_changes_baseline_step_id", "differential_changes", ["baseline_step_id"]
    )
    op.create_index(
        "ix_differential_changes_candidate_step_id",
        "differential_changes",
        ["candidate_step_id"],
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_REPORT_TRIGGER)
    op.execute(_CHANGE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_differential_changes_immutable ON differential_changes")
    op.execute("DROP TRIGGER IF EXISTS trg_differential_reports_immutable ON differential_reports")
    op.execute("DROP FUNCTION IF EXISTS prevent_differential_mutation")
    op.drop_table("differential_changes")
    op.drop_table("differential_reports")
