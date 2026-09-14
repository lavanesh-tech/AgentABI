"""replays: replay_runs, replay_steps

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_replay_status = postgresql.ENUM("pending", "running", "completed", "failed", name="replay_status")
_replay_step_kind = postgresql.ENUM(
    "reused_evidence",
    "substituted_execution",
    "provider_execution_required",
    "skipped",
    name="replay_step_kind",
)
_replay_step_status = postgresql.ENUM(
    "pending",
    "reused",
    "executed",
    "failed",
    "skipped",
    "provider_required",
    name="replay_step_status",
)

# `replay_steps` is append-only replay evidence, same posture as
# migration 0004's `trajectory_events`: a step row is only ever inserted
# once it's already in its final status (see `ReplayService`), so no
# column has a legitimate reason to change post-insert. `replay_runs`
# deliberately gets NO trigger, mirroring Phase 6's `trajectories` (ADR-027)
# — its `status`/`started_at`/`completed_at`/`error` are supposed to
# change over the run's PENDING->RUNNING->terminal lifecycle, protected
# only by `ReplayService` never offering any other mutation path.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_replay_step_mutation()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'replay_steps are immutable once created (id=%)', OLD.id;
END;
$$ LANGUAGE plpgsql;
"""

_STEP_TRIGGER = """
CREATE TRIGGER trg_replay_steps_immutable
BEFORE UPDATE ON replay_steps
FOR EACH ROW
EXECUTE FUNCTION prevent_replay_step_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    _replay_status.create(bind, checkfirst=True)
    _replay_step_kind.create(bind, checkfirst=True)
    _replay_step_status.create(bind, checkfirst=True)

    op.create_table(
        "replay_runs",
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
            "source_trajectory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trajectories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "baseline_component_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_component_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("component_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", _replay_status, nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_replay_runs_organization_id", "replay_runs", ["organization_id"])
    op.create_index("ix_replay_runs_project_id", "replay_runs", ["project_id"])
    op.create_index("ix_replay_runs_source_trajectory_id", "replay_runs", ["source_trajectory_id"])
    op.create_index("ix_replay_runs_component_id", "replay_runs", ["component_id"])
    # Idempotency key for create-replay retries (Phase 7 §12): unique per
    # project, only when set — same shape as migration 0004's
    # `uq_trajectories_project_external_run_id`.
    op.execute(
        "CREATE UNIQUE INDEX uq_replay_runs_project_idempotency_key "
        "ON replay_runs (project_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )

    op.create_table(
        "replay_steps",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "replay_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("replay_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "source_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("trajectory_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", _replay_step_kind, nullable=False),
        sa.Column("status", _replay_step_status, nullable=False),
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
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "replay_run_id", "sequence_number", name="uq_replay_steps_run_sequence"
        ),
    )
    op.create_index("ix_replay_steps_replay_run_id", "replay_steps", ["replay_run_id"])
    op.create_index("ix_replay_steps_source_event_id", "replay_steps", ["source_event_id"])
    op.create_index("ix_replay_steps_component_id", "replay_steps", ["component_id"])
    op.create_index(
        "ix_replay_steps_component_version_id", "replay_steps", ["component_version_id"]
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_STEP_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_replay_steps_immutable ON replay_steps")
    op.execute("DROP FUNCTION IF EXISTS prevent_replay_step_mutation")
    op.drop_table("replay_steps")
    op.drop_table("replay_runs")
    _replay_step_status.drop(op.get_bind(), checkfirst=True)
    _replay_step_kind.drop(op.get_bind(), checkfirst=True)
    _replay_status.drop(op.get_bind(), checkfirst=True)
