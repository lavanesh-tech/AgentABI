"""Centralized audit action taxonomy (Security Phase E spec §13). Pure
stdlib `enum` only — no SQLAlchemy import — mirrors
`app/authz/permissions.py`'s dependency-free design so this stays
`pytest --noconftest`-executable. `AuditEvent.action` stores
`AuditAction.value`, keyed by the plain string the same way
`OrganizationMember.role` stores `OrganizationRole.value`.

Deliberately scoped to actions this codebase's implemented security
features can actually emit today (spec §13) — not a speculative
taxonomy for unimplemented future features.
"""

import enum


class AuditAction(enum.StrEnum):
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILURE = "login_failure"
    AUTHORIZATION_DENIED = "authorization_denied"
    PROJECT_CREATED = "project_created"
    SCAN_TRIGGERED = "scan_triggered"
    REPLAY_TRIGGERED = "replay_triggered"
    GITHUB_WEBHOOK_PROCESSED = "github_webhook_processed"
    GITHUB_WEBHOOK_REJECTED = "github_webhook_rejected"
    GITHUB_PR_ANALYSIS_STARTED = "github_pr_analysis_started"
    GITHUB_PR_ANALYSIS_COMPLETED = "github_pr_analysis_completed"
    GITHUB_CHECK_PUBLISHED = "github_check_published"
    GITHUB_CHECK_FAILED = "github_check_failed"
    KAFKA_ANALYSIS_ENQUEUED = "kafka_analysis_enqueued"
    KAFKA_ANALYSIS_STARTED = "kafka_analysis_started"
    KAFKA_ANALYSIS_COMPLETED = "kafka_analysis_completed"
    KAFKA_ANALYSIS_FAILED = "kafka_analysis_failed"
