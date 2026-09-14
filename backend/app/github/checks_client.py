"""GitHub Checks API client (Phase 12). The only module that speaks
HTTP to the GitHub Checks API — `app/services/github_pr_analysis_
service.py` depends on the `GitHubChecksClient` Protocol
(`checks_models.py`), never on `httpx` directly (spec §9).

`httpx` is a declared dependency (pyproject.toml) but not installable
in this sandbox (same PyPI-403 restriction as every prior phase), so
this module is written and `py_compile`-clean but not exercised by
`pytest` here — `app/services/github_pr_analysis_service.py` is tested
against `FakeGitHubChecksClient` instead (`checks_fake.py`).
"""

import asyncio
from dataclasses import dataclass

import httpx

from app.domain.exceptions import (
    GitHubAPIUnavailable,
    GitHubAuthenticationFailed,
    GitHubCheckPublishFailed,
)
from app.github.checks_models import (
    CheckRunRequest,
    CheckRunResult,
    CheckStatus,
    GitHubCredentialProvider,
)
from app.observability import start_span

CHECKS_API_BASE = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"

# Bounded, transient-only retries (spec §29): a 5xx or a network-level
# timeout is retried; an auth failure (401/403) or a validation failure
# (4xx other than 429) is not — retrying those would just repeat the
# same failure and risk a retry storm against a misconfigured
# credential.
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5


@dataclass(frozen=True)
class StaticGitHubCredentialProvider:
    """Reads `Settings.github_checks_token` — see that field's docstring
    for why this isn't a full GitHub App JWT-then-installation-token
    exchange yet. Implements `GitHubCredentialProvider` structurally."""

    token: str | None

    async def get_token(self) -> str:
        if not self.token:
            raise GitHubAuthenticationFailed("github_checks_token is not configured")
        return self.token


def _conclusion_value(request: CheckRunRequest) -> str | None:
    return request.conclusion.value if request.conclusion is not None else None


def _body(request: CheckRunRequest) -> dict:
    body: dict = {
        "name": request.name,
        "head_sha": request.head_sha,
        "status": request.status.value,
        "output": {"title": request.output.title, "summary": request.output.summary},
    }
    conclusion = _conclusion_value(request)
    if conclusion is not None:
        body["conclusion"] = conclusion
    if request.details_url:
        body["details_url"] = request.details_url
    if request.external_id:
        body["external_id"] = request.external_id
    return body


def _result_from_response(data: dict) -> CheckRunResult:
    return CheckRunResult(
        id=int(data["id"]),
        status=CheckStatus(data["status"]),
        conclusion=data.get("conclusion"),
        html_url=data.get("html_url"),
    )


@dataclass(frozen=True)
class HttpxGitHubChecksClient:
    """Production implementation. Never logs the resolved bearer token
    or the `Authorization` header (spec §31) — only operation/repository/
    status-category metadata, matching Phase 8's `OpenAIProvider` logging
    discipline."""

    credentials: GitHubCredentialProvider
    timeout_seconds: float = 10.0

    async def create_check_run(self, request: CheckRunRequest) -> CheckRunResult:
        url = f"{CHECKS_API_BASE}/repos/{request.repository_full_name}/check-runs"
        with start_span(
            "github.check.create",
            kind="client",
            attributes={
                "agentabi.github_repository_full_name": request.repository_full_name,
                "agentabi.head_sha": request.head_sha,
            },
        ):
            return await self._send("POST", url, request)

    async def update_check_run(
        self, *, repository_full_name: str, check_run_id: int, request: CheckRunRequest
    ) -> CheckRunResult:
        url = f"{CHECKS_API_BASE}/repos/{repository_full_name}/check-runs/{check_run_id}"
        with start_span(
            "github.check.update",
            kind="client",
            attributes={
                "agentabi.github_repository_full_name": repository_full_name,
                "agentabi.check_run_id": check_run_id,
                "agentabi.head_sha": request.head_sha,
            },
        ):
            return await self._send("PATCH", url, request)

    async def _send(self, method: str, url: str, request: CheckRunRequest) -> CheckRunResult:
        token = await self.credentials.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _GITHUB_API_VERSION,
        }
        body = _body(request)

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.request(method, url, headers=headers, json=body)
            except httpx.TimeoutException as exc:
                last_exc = exc
            except httpx.HTTPError as exc:
                # Network-level failure (connect error, etc.) — treated
                # as transient/retryable, same bucket as a timeout.
                last_exc = exc
            else:
                if response.status_code in (401, 403):
                    raise GitHubAuthenticationFailed(
                        f"GitHub rejected the checks credential (HTTP {response.status_code})"
                    )
                if response.status_code >= 500:
                    last_exc = GitHubAPIUnavailable(
                        f"GitHub Checks API returned {response.status_code}"
                    )
                elif response.status_code >= 400:
                    # Non-auth 4xx (validation, 404 repo/ref, 422, ...) —
                    # never retried, never treated as "transiently
                    # unavailable".
                    raise GitHubCheckPublishFailed(
                        f"GitHub Checks API rejected the request (HTTP {response.status_code})"
                    )
                else:
                    try:
                        return _result_from_response(response.json())
                    except (ValueError, KeyError, TypeError) as exc:
                        raise GitHubCheckPublishFailed(
                            "GitHub Checks API returned a malformed response"
                        ) from exc

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))

        raise GitHubAPIUnavailable(
            f"GitHub Checks API unavailable after {_MAX_RETRIES + 1} attempts"
        ) from last_exc
