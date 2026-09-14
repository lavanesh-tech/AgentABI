"""risk assessments: risk_assessments, risk_rule_results

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# risk_assessments/risk_rule_results are derived, immutable evidence
# (Phase 11 spec §22) — same pattern as migration 0008's
# `prevent_differential_mutation`. UPDATE only (not DELETE): no
# security requirement here that an assessment survive an intentional
# project/scan/report cascade delete.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_risk_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        '% are immutable once created (id=%)', TG_TABLE_NAME, OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_ASSESSMENT_TRIGGER = """
CREATE TRIGGER trg_risk_assessments_immutable
BEFORE UPDATE ON risk_assessments
FOR EACH ROW
EXECUTE FUNCTION prevent_risk_mutation();
"""

_RULE_RESULT_TRIGGER = """
CREATE TRIGGER trg_risk_rule_results_immutable
BEFORE UPDATE ON risk_rule_results
FOR EACH ROW
EXECUTE FUNCTION prevent_risk_mutation();
"""


def upgrade() -> None:
    op.create_table(
        "risk_assessments",
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
            "compatibility_scan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compatibility_scans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "differential_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("differential_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("risk_engine_version", sa.String(length=20), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("hard_block", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "project_id",
            "compatibility_scan_id",
            "differential_report_id",
            "risk_engine_version",
            name="uq_risk_assessments_idempotency",
        ),
    )
    op.create_index("ix_risk_assessments_organization_id", "risk_assessments", ["organization_id"])
    op.create_index("ix_risk_assessments_project_id", "risk_assessments", ["project_id"])
    op.create_index(
        "ix_risk_assessments_compatibility_scan_id", "risk_assessments", ["compatibility_scan_id"]
    )
    op.create_index(
        "ix_risk_assessments_differential_report_id",
        "risk_assessments",
        ["differential_report_id"],
    )

    op.create_table(
        "risk_rule_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("risk_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("score_delta", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hard_block", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_risk_rule_results_assessment_id", "risk_rule_results", ["assessment_id"])

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_ASSESSMENT_TRIGGER)
    op.execute(_RULE_RESULT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_risk_rule_results_immutable ON risk_rule_results")
    op.execute("DROP TRIGGER IF EXISTS trg_risk_assessments_immutable ON risk_assessments")
    op.execute("DROP FUNCTION IF EXISTS prevent_risk_mutation")
    op.drop_table("risk_rule_results")
    op.drop_table("risk_assessments")
