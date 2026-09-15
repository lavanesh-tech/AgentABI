"""trajectories: trajectories, trajectory_events

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False on both: see 0001_initial_schema.py's
# _organization_role comment — without it, the op.create_table() calls
# below would each auto-CREATE TYPE a second time, duplicating the
# explicit .create() calls further down.
_trajectory_status = postgresql.ENUM(
    "running", "completed", "failed", name="trajectory_status", create_type=False
)
_trajectory_event_type = postgresql.ENUM(
    "run_started",
    "run_completed",
    "run_failed",
    "agent_started",
    "agent_completed",
    "model_request",
    "model_response",
    "tool_call",
    "tool_response",
    "mcp_request",
    "mcp_response",
    "api_request",
    "api_response",
    "state_read",
    "state_write",
    "decision",
    "structured_output",
    "error",
    name="trajectory_event_type",
    create_type=False,
)

# `trajectory_events` is append-only historical evidence, same posture as
# migration 0003's `compatibility_scans`/`scan_changes` — no column on
# this table has a legitimate reason to change post-insert. `trajectories`
# deliberately gets NO trigger: unlike scan evidence, a trajectory's
# `status`/`completed_at`/`error`/`next_sequence`/`updated_at` are
# supposed to change over its RUNNING lifetime — that's protected by
# `TrajectoryRecorderService` never offering a way to touch anything else
# (the same "no trigger, service-layer discipline only" posture Phase 3's
# `components` identity table already uses). See docs/DECISIONS.md.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_trajectory_event_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'trajectory_events are immutable once created (id=%)', OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_EVENT_TRIGGER = """
CREATE TRIGGER trg_trajectory_events_immutable
BEFORE UPDATE ON trajectory_events
FOR EACH ROW
EXECUTE FUNCTION prevent_trajectory_event_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    _trajectory_status.create(bind, checkfirst=True)
    _trajectory_event_type.create(bind, checkfirst=True)

    op.create_table(
        "trajectories",
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
            "workflow_component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "workflow_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("external_run_id", sa.String(length=255), nullable=True),
        sa.Column("status", _trajectory_status, nullable=False, server_default="running"),
        sa.Column("environment", sa.String(length=100), nullable=True),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("trace_id", sa.String(length=255), nullable=True),
        sa.Column("span_id", sa.String(length=255), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_trajectories_organization_id", "trajectories", ["organization_id"])
    op.create_index("ix_trajectories_project_id", "trajectories", ["project_id"])
    op.create_index(
        "ix_trajectories_workflow_component_id", "trajectories", ["workflow_component_id"]
    )
    op.create_index("ix_trajectories_correlation_id", "trajectories", ["correlation_id"])
    # Idempotency key for start-trajectory retries (Phase 6 §13):
    # unique per project, only when set — two different projects may
    # legitimately reuse the same external run-id scheme, and a
    # trajectory with no external_run_id shouldn't collide with any
    # other unset one.
    op.execute(
        "CREATE UNIQUE INDEX uq_trajectories_project_external_run_id "
        "ON trajectories (project_id, external_run_id) "
        "WHERE external_run_id IS NOT NULL"
    )

    op.create_table(
        "trajectory_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "trajectory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trajectories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", _trajectory_event_type, nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "component_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "parent_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trajectory_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("correlation_id", sa.String(length=255), nullable=True),
        sa.Column("external_event_id", sa.String(length=255), nullable=True),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "payload_truncated", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("payload_original_size_bytes", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint(
            "trajectory_id", "sequence_number", name="uq_trajectory_events_trajectory_sequence"
        ),
    )
    op.create_index("ix_trajectory_events_trajectory_id", "trajectory_events", ["trajectory_id"])
    op.create_index("ix_trajectory_events_event_type", "trajectory_events", ["event_type"])
    op.create_index("ix_trajectory_events_component_id", "trajectory_events", ["component_id"])
    op.create_index(
        "ix_trajectory_events_component_version_id",
        "trajectory_events",
        ["component_version_id"],
    )
    # Idempotency key for event-ingestion retries (Phase 6 §14): unique
    # per trajectory, only when set.
    op.execute(
        "CREATE UNIQUE INDEX uq_trajectory_events_trajectory_external_event_id "
        "ON trajectory_events (trajectory_id, external_event_id) "
        "WHERE external_event_id IS NOT NULL"
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_EVENT_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_trajectory_events_immutable ON trajectory_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_trajectory_event_mutation")
    op.drop_table("trajectory_events")
    op.drop_table("trajectories")
    _trajectory_event_type.drop(op.get_bind(), checkfirst=True)
    _trajectory_status.drop(op.get_bind(), checkfirst=True)
