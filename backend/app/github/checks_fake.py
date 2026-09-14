"""`FakeGitHubChecksClient` — an in-memory `GitHubChecksClient`
implementation for tests (spec §9/§35/§41: "no real network in normal
tests"). Mirrors `app.providers.fake_provider.FakeLLMProvider`'s reason
for living in the production tree rather than a test file: more than one
test module needs it (`test_github_checks_client_mapping.py`,
`test_github_pr_analysis_service.py`).
"""

from dataclasses import dataclass, field

from app.domain.exceptions import GitHubAPIUnavailable
from app.github.checks_models import (
    CheckRunRequest,
    CheckRunResult,
    CheckStatus,
    RecordedCheckCall,
)

_NEXT_ID_START = 1000


@dataclass
class FakeGitHubChecksClient:
    """Records every call for test assertions. Set `fail_with` to an
    exception instance to make the next call raise it (simulating a
    provider failure) — cleared after raising once, so a test can
    assert a single failure without wedging every subsequent call."""

    calls: list[RecordedCheckCall] = field(default_factory=list)
    fail_with: Exception | None = None
    _next_id: int = _NEXT_ID_START

    async def create_check_run(self, request: CheckRunRequest) -> CheckRunResult:
        self._maybe_fail()
        check_run_id = self._next_id
        self._next_id += 1
        self.calls.append(
            RecordedCheckCall(
                operation="create",
                repository_full_name=request.repository_full_name,
                head_sha=request.head_sha,
                status=request.status,
                conclusion=request.conclusion,
                check_run_id=check_run_id,
            )
        )
        return CheckRunResult(
            id=check_run_id,
            status=request.status,
            conclusion=request.conclusion,
            html_url=f"https://github.com/{request.repository_full_name}/runs/{check_run_id}",
        )

    async def update_check_run(
        self, *, repository_full_name: str, check_run_id: int, request: CheckRunRequest
    ) -> CheckRunResult:
        self._maybe_fail()
        self.calls.append(
            RecordedCheckCall(
                operation="update",
                repository_full_name=repository_full_name,
                head_sha=request.head_sha,
                status=request.status,
                conclusion=request.conclusion,
                check_run_id=check_run_id,
            )
        )
        return CheckRunResult(
            id=check_run_id,
            status=request.status,
            conclusion=request.conclusion,
            html_url=f"https://github.com/{repository_full_name}/runs/{check_run_id}",
        )

    def _maybe_fail(self) -> None:
        if self.fail_with is not None:
            exc, self.fail_with = self.fail_with, None
            raise exc


def failing_checks_client(
    reason: str = "simulated GitHub outage",
) -> FakeGitHubChecksClient:
    """Convenience constructor for the common "publishing fails" test
    case (spec §28: GitHub API failure must not corrupt evidence)."""

    return FakeGitHubChecksClient(fail_with=GitHubAPIUnavailable(reason))


# Re-exported so a caller only needs one import for the common status
# constant used when asserting "no conclusion yet" on an in-progress call.
__all__ = ["FakeGitHubChecksClient", "failing_checks_client", "CheckStatus"]
