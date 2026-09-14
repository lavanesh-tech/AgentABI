"""GitHubPullRequestAnalysis — persisted state for one logical PR
analysis run (Phase 12 spec §22): which deterministic evidence it
produced, whether/how the GitHub check was published, and the exact
`head_sha` it applies to (spec §25's stale-result protection — every
row is pinned to the one commit it analyzed, never "the latest" by
implication).

Unlike `RiskAssessmentRecord`/`DifferentialReportRecord`, this is NOT
immutable-once-created (no migration trigger): `status`/`check_run_id`/
`risk_assessment_id` legitimately update as the pipeline progresses
(queued analysis -> deterministic result computed -> check published or
publish failed) — see docs/DECISIONS.md for why this table deliberately
does not follow the Phase 10/11 immutable-evidence pattern.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.github.pr_analysis_models import GitHubPRAnalysisStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GitHubPullRequestAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_pr_analyses"
    __table_args__ = (
        # Logical idempotency key (spec §23): the same repository/PR/
        # head_sha/analysis_version never produces two analysis rows —
        # a redelivered webhook for a commit already analyzed reuses
        # the existing row rather than recomputing or republishing.
        UniqueConstraint(
            "github_repository_id",
            "pull_request_number",
            "head_sha",
            "analysis_version",
            name="uq_github_pr_analyses_idempotency",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    github_repository_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    pull_request_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Pinned exact-SHA identity (spec §25): a later commit's analysis
    # never overwrites or is confused with an earlier one's.
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)

    delivery_id: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Plain VARCHAR, not a Postgres native enum (same "grows over time,
    # avoid an extra CREATE TYPE migration" tradeoff as `scan_changes.
    # change_type` — see docs/DECISIONS.md) — stores
    # `GitHubPRAnalysisStatus.value`; callers construct/compare via that
    # enum, never a raw string literal.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=GitHubPRAnalysisStatus.PENDING.value
    )
    # Denormalized for quick listing/filtering without a join — the
    # authoritative decision still lives on `RiskAssessmentRecord`.
    decision: Mapped[str | None] = mapped_column(String(10), nullable=True)

    compatibility_scan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("compatibility_scans.id", ondelete="SET NULL"), nullable=True
    )
    risk_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("risk_assessments.id", ondelete="SET NULL"), nullable=True
    )
    check_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Small, safe metadata only (spec §26/§31): never a token, never a
    # raw webhook payload.
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"GitHubPullRequestAnalysis(github_repository_id={self.github_repository_id!r}, "
            f"pull_request_number={self.pull_request_number!r}, head_sha={self.head_sha!r}, "
            f"status={self.status!r})"
        )
