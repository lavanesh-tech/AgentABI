"""security audit and github webhooks: audit_events, github_webhook_deliveries

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False on both: see 0001_initial_schema.py's
# _organization_role comment — without it, the op.create_table() calls
# below would each auto-CREATE TYPE a second time, duplicating the
# explicit .create() calls further down.
_audit_action = postgresql.ENUM(
    "login_success",
    "login_failure",
    "authorization_denied",
    "project_created",
    "scan_triggered",
    "replay_triggered",
    "github_webhook_processed",
    "github_webhook_rejected",
    name="audit_action",
    create_type=False,
)
_webhook_delivery_status = postgresql.ENUM(
    "processed", "rejected", name="github_webhook_delivery_status", create_type=False
)

# audit_events is append-only evidence of security-relevant actions —
# once written it should never change. Same pattern as migration 0003's
# `prevent_compatibility_evidence_mutation`: the service layer exposes
# no update/delete path, and this is the database-level backstop for a
# write that bypasses it. Unlike prior immutability triggers (UPDATE
# only), this one also blocks DELETE — the audit trail must survive
# even an attempt to erase individual rows (spec §16).
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_audit_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events are immutable and append-only (id=%)',
        COALESCE(OLD.id, NEW.id);
END;
$$ LANGUAGE plpgsql;
"""

_UPDATE_TRIGGER = """
CREATE TRIGGER trg_audit_events_immutable_update
BEFORE UPDATE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_event_mutation();
"""

_DELETE_TRIGGER = """
CREATE TRIGGER trg_audit_events_immutable_delete
BEFORE DELETE ON audit_events
FOR EACH ROW
EXECUTE FUNCTION prevent_audit_event_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    _audit_action.create(bind, checkfirst=True)
    _webhook_delivery_status.create(bind, checkfirst=True)

    op.create_table(
        "github_webhook_deliveries",
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
        sa.Column("delivery_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("status", _webhook_delivery_status, nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    # Idempotency backstop (spec §8): a unique constraint, not just an
    # application-level pre-check, so two concurrent deliveries with the
    # same X-GitHub-Delivery id can never both insert.
    op.create_unique_constraint(
        "uq_github_webhook_deliveries_delivery_id", "github_webhook_deliveries", ["delivery_id"]
    )
    op.create_index(
        "ix_github_webhook_deliveries_delivery_id", "github_webhook_deliveries", ["delivery_id"]
    )
    op.create_index(
        "ix_github_webhook_deliveries_event_type", "github_webhook_deliveries", ["event_type"]
    )

    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", _audit_action, nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    # Tenant-scoped listing (spec §18) always filters by organization_id
    # and orders by recency — a composite index serves that query
    # directly instead of a full index scan plus sort.
    op.create_index(
        "ix_audit_events_org_created_at", "audit_events", ["organization_id", "created_at"]
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_UPDATE_TRIGGER)
    op.execute(_DELETE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable_delete ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable_update ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation")
    op.drop_table("audit_events")
    op.drop_index("ix_github_webhook_deliveries_event_type", table_name="github_webhook_deliveries")
    op.drop_index(
        "ix_github_webhook_deliveries_delivery_id", table_name="github_webhook_deliveries"
    )
    op.drop_constraint(
        "uq_github_webhook_deliveries_delivery_id",
        "github_webhook_deliveries",
        type_="unique",
    )
    op.drop_table("github_webhook_deliveries")
    _webhook_delivery_status.drop(op.get_bind(), checkfirst=True)
    _audit_action.drop(op.get_bind(), checkfirst=True)
