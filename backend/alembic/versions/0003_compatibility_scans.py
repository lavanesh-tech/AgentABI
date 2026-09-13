"""compatibility scans: compatibility_scans, scan_changes

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_compatibility_status = postgresql.ENUM(
    "compatible", "warning", "breaking", name="compatibility_status"
)
_compatibility_classification = postgresql.ENUM(
    "compatible", "potentially_breaking", "breaking", name="compatibility_classification"
)
_compatibility_severity = postgresql.ENUM(
    "info", "low", "medium", "high", "critical", name="compatibility_severity"
)

# A compatibility scan (and its changes) is evidence for a release
# decision: once written, it should never silently change. Same pattern
# as migration 0002's `prevent_component_version_mutation` trigger —
# service/API exposes no update path, and this is the database-level
# backstop for a write that bypasses both.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_compatibility_evidence_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'compatibility scan evidence is immutable once created (table=%, id=%)',
        TG_TABLE_NAME, OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_SCAN_TRIGGER = """
CREATE TRIGGER trg_compatibility_scans_immutable
BEFORE UPDATE ON compatibility_scans
FOR EACH ROW
EXECUTE FUNCTION prevent_compatibility_evidence_mutation();
"""

_CHANGE_TRIGGER = """
CREATE TRIGGER trg_scan_changes_immutable
BEFORE UPDATE ON scan_changes
FOR EACH ROW
EXECUTE FUNCTION prevent_compatibility_evidence_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    _compatibility_status.create(bind, checkfirst=True)
    _compatibility_classification.create(bind, checkfirst=True)
    _compatibility_severity.create(bind, checkfirst=True)

    op.create_table(
        "compatibility_scans",
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
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "baseline_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", _compatibility_status, nullable=False),
        sa.Column("total_changes", sa.Integer(), nullable=False),
        sa.Column("compatible_count", sa.Integer(), nullable=False),
        sa.Column("potentially_breaking_count", sa.Integer(), nullable=False),
        sa.Column("breaking_count", sa.Integer(), nullable=False),
        sa.Column("severity_info_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity_low_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity_medium_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity_high_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("severity_critical_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_compatibility_scans_project_id", "compatibility_scans", ["project_id"])
    op.create_index("ix_compatibility_scans_component_id", "compatibility_scans", ["component_id"])

    op.create_table(
        "scan_changes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compatibility_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("change_type", sa.String(length=100), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("classification", _compatibility_classification, nullable=False),
        sa.Column("severity", _compatibility_severity, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("old_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_scan_changes_scan_id", "scan_changes", ["scan_id"])
    op.create_index("ix_scan_changes_change_type", "scan_changes", ["change_type"])

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_SCAN_TRIGGER)
    op.execute(_CHANGE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_scan_changes_immutable ON scan_changes")
    op.execute("DROP TRIGGER IF EXISTS trg_compatibility_scans_immutable ON compatibility_scans")
    op.execute("DROP FUNCTION IF EXISTS prevent_compatibility_evidence_mutation")
    op.drop_table("scan_changes")
    op.drop_table("compatibility_scans")
    _compatibility_severity.drop(op.get_bind(), checkfirst=True)
    _compatibility_classification.drop(op.get_bind(), checkfirst=True)
    _compatibility_status.drop(op.get_bind(), checkfirst=True)
