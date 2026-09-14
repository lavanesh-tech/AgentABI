"""Pure lifecycle enum for `GitHubPullRequestAnalysis` (Phase 12). Kept
dependency-free like `app/github/webhook_models.py`'s
`WebhookDeliveryStatus` — no SQLAlchemy import, so it's importable from
both the ORM model and any pure test.
"""

import enum


class GitHubPRAnalysisStatus(enum.StrEnum):
    """Unlike Phase 10/11's evidence tables, a PR analysis row is
    operational lifecycle state, not immutable derived evidence — it
    legitimately transitions as the pipeline progresses (spec §21/§28):
    the deterministic assessment can complete while publishing the
    GitHub check still fails, and that failure must remain visible and
    safely retryable rather than silently discarded."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PUBLISH_FAILED = "publish_failed"
    FAILED = "failed"
