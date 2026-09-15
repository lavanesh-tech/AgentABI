"""component registry: components, component_versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False on both: see 0001_initial_schema.py's
# _organization_role comment — without it, op.create_table("components",
# ...)/op.create_table("component_versions", ...) below would each try
# to auto-CREATE TYPE a second time for whichever of these two enums
# they use as a column type, duplicating the explicit .create() calls
# further down and raising DuplicateObjectError.
_component_type = postgresql.ENUM(
    "agent",
    "prompt",
    "model",
    "provider",
    "mcp_server",
    "tool",
    "schema",
    "api",
    "workflow",
    "policy",
    name="component_type",
    create_type=False,
)
_component_status = postgresql.ENUM(
    "active", "deprecated", "archived", name="component_status", create_type=False
)

# Database-level backstop for version immutability: even a write that
# bypasses the ORM/service layer entirely cannot change a version's
# content or checksum once inserted.
_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_component_version_mutation()
RETURNS trigger AS $$
BEGIN
    IF NEW.content IS DISTINCT FROM OLD.content
       OR NEW.checksum IS DISTINCT FROM OLD.checksum THEN
        RAISE EXCEPTION
            'component_versions.content/checksum are immutable (id=%)', OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_IMMUTABILITY_TRIGGER = """
CREATE TRIGGER trg_component_versions_immutable
BEFORE UPDATE ON component_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_component_version_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    _component_type.create(bind, checkfirst=True)
    _component_status.create(bind, checkfirst=True)

    op.create_table(
        "components",
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
        sa.Column("component_type", _component_type, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", _component_status, nullable=False, server_default="active"),
        sa.UniqueConstraint(
            "project_id", "component_type", "slug", name="uq_components_project_type_slug"
        ),
    )
    op.create_index("ix_components_organization_id", "components", ["organization_id"])
    op.create_index("ix_components_project_id", "components", ["project_id"])
    op.create_index("ix_components_component_type", "components", ["component_type"])

    op.create_table(
        "component_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "component_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("components.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "component_id", "version", name="uq_component_versions_component_id_version"
        ),
        sa.UniqueConstraint("sequence", name="uq_component_versions_sequence"),
    )
    op.create_index("ix_component_versions_component_id", "component_versions", ["component_id"])
    op.create_index("ix_component_versions_checksum", "component_versions", ["checksum"])
    op.create_index(
        "ix_component_versions_component_id_sequence",
        "component_versions",
        ["component_id", sa.text("sequence DESC")],
    )

    op.execute(_IMMUTABILITY_FUNCTION)
    op.execute(_IMMUTABILITY_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_component_versions_immutable ON component_versions")
    op.execute("DROP FUNCTION IF EXISTS prevent_component_version_mutation")
    op.drop_table("component_versions")
    op.drop_table("components")
    _component_status.drop(op.get_bind(), checkfirst=True)
    _component_type.drop(op.get_bind(), checkfirst=True)
