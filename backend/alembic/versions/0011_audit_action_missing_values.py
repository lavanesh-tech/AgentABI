"""audit_action: add values missing from the Postgres enum

The `audit_action` Postgres enum was created by migration 0007 with only
the 8 `AuditAction` members that existed at that time. `app/audit/
actions.py` (the application-layer source of truth) has since grown
more members — most recently `ORGANIZATION_CREATED` (the first-
organization onboarding feature), which is what surfaced this as a real
runtime failure: `AuditService.record(action=AuditAction.
ORGANIZATION_CREATED, ...)` inserts the Python enum's `.value` string
`"organization_created"` into the `action` column, and
`asyncpg.exceptions.InvalidTextRepresentationError` is raised at commit
because Postgres's `audit_action` type has no such label.

Inspecting every migration confirmed `audit_action` was never altered
after 0007, while `AuditAction` had already grown several other members
with no corresponding migration (`github_pr_analysis_started`,
`github_pr_analysis_completed`, `github_check_published`,
`github_check_failed`, and the four `kafka_analysis_*` values, added by
Phase 12/13 without ever migrating the enum type — apparently never
actually recorded via `AuditService` yet, which is the only reason those
gaps hadn't already raised the same error). This migration is a single,
comprehensive fix: it adds every `AuditAction` value the database is
currently missing, not just `organization_created`, so the drift this
whole class of bug represents is fully closed rather than deferred one
value at a time. This is purely additive and touches no existing rows.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-15
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every `AuditAction` member that was missing from the `audit_action`
# Postgres enum as of this migration (see module docstring). Kept as an
# explicit literal list — not computed from `app.audit.actions.
# AuditAction` — so this migration's behavior is fixed at the moment it
# was written and never silently changes if the application enum grows
# again later (a future gap gets its own future migration, the same way
# this one exists).
_MISSING_VALUES: tuple[str, ...] = (
    "organization_created",
    "github_pr_analysis_started",
    "github_pr_analysis_completed",
    "github_check_published",
    "github_check_failed",
    "kafka_analysis_enqueued",
    "kafka_analysis_started",
    "kafka_analysis_completed",
    "kafka_analysis_failed",
)


def upgrade() -> None:
    # `ALTER TYPE ... ADD VALUE` cannot safely run as an ordinary
    # statement inside Alembic's per-migration transaction (PostgreSQL
    # forbids using a value added this way in the same transaction that
    # added it, and versions before 12 forbid the ALTER itself inside a
    # transaction block at all). `autocommit_block()` is Alembic's
    # documented mechanism for exactly this: each statement below runs
    # in its own implicitly-committed transaction, so every added value
    # is immediately usable by the very next `INSERT` this API serves.
    with op.get_context().autocommit_block():
        for value in _MISSING_VALUES:
            op.execute(f"ALTER TYPE audit_action ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL has no `ALTER TYPE ... DROP VALUE`. Removing a value
    # from a native enum safely requires recreating the type (rename the
    # old type, `CREATE TYPE` the new one without the value, `ALTER
    # TABLE ... ALTER COLUMN ... TYPE new_type USING ...`, then drop the
    # old type) — and that recreation is only safe if no existing row
    # uses any of the values being dropped, or if the operator is
    # willing to remap/delete those rows first. `audit_events` is an
    # append-only, immutable, security-relevant audit trail (migration
    # 0007's `prevent_audit_event_mutation` trigger enforces this at the
    # database level); silently deleting or remapping audit rows as a
    # side effect of a downgrade would violate that invariant and is
    # exactly the kind of destructive downgrade this codebase's audit
    # design exists to prevent (see docs/DECISIONS.md ADR-049).
    #
    # This migration is additive-only by design (see `upgrade()`), so a
    # true downgrade is refused rather than silently doing nothing or
    # destroying data — the operator must explicitly decide how to
    # handle any rows already recorded with these actions before an
    # enum-recreation downgrade could ever be safe to write.
    raise RuntimeError(
        "0011 cannot be downgraded automatically: removing values from the "
        "audit_action enum requires recreating the type, which is only safe "
        "after auditing audit_events for rows using "
        f"{_MISSING_VALUES!r} and deciding how to handle them. audit_events "
        "is an append-only, immutable audit trail (migration 0007) — this "
        "migration will not risk destroying or remapping audit data "
        "automatically. If a downgrade is truly required, perform that "
        "review manually first, then write a follow-up migration that "
        "recreates the enum type explicitly."
    )
