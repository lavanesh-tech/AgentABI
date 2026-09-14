"""GitHubRepositoryMapping — the deterministic mapping between a GitHub
repository and an AgentABI project (Phase 12 spec §7), plus the explicit
analysis contract for that repository (spec §19/§20/§21): no inference
from a git diff, ever — a repository must be mapped to a `component_id`
and, optionally, a fixed `baseline_version` string, both configured
through the management API (`app/api/v1/github_repositories.py`), never
derived automatically.

Keyed by GitHub's immutable numeric repository id (`github_repository_id`,
globally unique across GitHub) — never `owner/repo`, which changes on a
rename/transfer (spec §7).
"""

import uuid

from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class GitHubRepositoryMapping(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_repository_mappings"
    __table_args__ = (
        # A GitHub repository id is globally unique across GitHub, so it
        # can only ever map to one AgentABI project — not scoped to
        # organization_id (spec §7).
        UniqueConstraint("github_repository_id", name="uq_github_repository_mappings_repo_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Which AgentABI component a pull request in this repository is
    # analyzed against (spec §19's explicit contract) — nullable only
    # until an ADMIN configures it; a mapping with no component_id
    # cannot start analysis (`MissingAgentABIConfiguration`).
    component_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("components.id", ondelete="SET NULL"), nullable=True
    )

    github_repository_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # Informational only, refreshed on each webhook — never the lookup
    # key (spec §7: a repo can be renamed/transferred).
    github_repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    github_installation_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Explicit, versioned-in-the-obvious-sense (a free-form
    # `ComponentVersion.version` string, spec §20) baseline to compare
    # every PR's candidate against. Null means "use the component's
    # latest registered version" (`GitHubPullRequestAnalysisService`'s
    # documented default — see docs/DECISIONS.md).
    baseline_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"GitHubRepositoryMapping(github_repository_id={self.github_repository_id!r}, "
            f"project_id={self.project_id!r})"
        )
