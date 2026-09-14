"""Typed shapes for the GitHub Checks API (Phase 12). No `httpx` import
here (mirrors `app/github/oauth_models.py`'s reason for existing) — the
`GitHubChecksClient` Protocol and its request/result dataclasses live
here so `app/services/github_pr_analysis_service.py` and its tests can
depend on this module without pulling in `httpx`, unavailable in this
sandbox.
"""

import enum
from dataclasses import dataclass
from typing import Protocol


class CheckStatus(enum.StrEnum):
    """GitHub Checks API `status` values this integration actually
    uses (spec §11) — not the full GitHub enum."""

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class CheckConclusion(enum.StrEnum):
    """GitHub Checks API `conclusion` values AgentABI ever sends (spec
    §12) — a deliberately narrow subset of GitHub's full set (which also
    includes cancelled/timed_out/action_required/stale/skipped): this
    integration only ever produces one of these three, one per Phase 11
    `RiskDecision`."""

    SUCCESS = "success"
    NEUTRAL = "neutral"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class CheckRunOutput:
    """The check run's user-visible body (spec §13) — title + a concise
    markdown summary. Never a raw JSON dump of deterministic evidence."""

    title: str
    summary: str


@dataclass(frozen=True, slots=True)
class CheckRunRequest:
    """Everything needed to create or update one check run. `external_id`
    carries AgentABI's own `GitHubPullRequestAnalysis.id` so the check
    run round-trips back to the exact analysis that produced it."""

    repository_full_name: str
    head_sha: str
    name: str
    status: CheckStatus
    output: CheckRunOutput
    conclusion: CheckConclusion | None = None
    details_url: str | None = None
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class CheckRunResult:
    """The provider's response to a create/update call — the only shape
    of a GitHub Checks API response anything past `app/github/
    checks_client.py` ever sees (mirrors `GitHubTokenResponse`/
    `GitHubIdentity`'s reason for existing)."""

    id: int
    status: CheckStatus
    conclusion: CheckConclusion | None
    html_url: str | None = None


class GitHubCredentialProvider(Protocol):
    """Resolves the bearer token used for GitHub API calls, kept behind
    a Protocol so the credential *strategy* (static token today, a real
    GitHub App JWT-then-installation-token exchange later) can change
    without touching `GitHubChecksClient` or its callers (spec §8's
    "keep authentication clearly separated ... credential/provider
    abstraction that supports test fakes")."""

    async def get_token(self) -> str: ...


class GitHubChecksClient(Protocol):
    """The abstraction `GitHubPullRequestAnalysisService` depends on.
    Application/service code never touches a raw `httpx.Response`
    (spec §9) — `HttpxGitHubChecksClient` (production, `checks_client.py`)
    and `FakeGitHubChecksClient` (tests, `checks_fake.py`) both implement
    this structurally."""

    async def create_check_run(self, request: CheckRunRequest) -> CheckRunResult: ...

    async def update_check_run(
        self, *, repository_full_name: str, check_run_id: int, request: CheckRunRequest
    ) -> CheckRunResult: ...


@dataclass(frozen=True, slots=True)
class RecordedCheckCall:
    """One call `FakeGitHubChecksClient` recorded, for test assertions —
    kept here (not test-local) since more than one test module asserts
    against it."""

    operation: str
    repository_full_name: str
    head_sha: str
    status: CheckStatus
    conclusion: CheckConclusion | None
    check_run_id: int | None = None
