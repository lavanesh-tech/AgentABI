"""GitHubOAuthService — orchestration tests using `FakeGitHubOAuthClient`
+ `InMemoryOAuthStateStore` (Security Phase B spec §16: "no real GitHub
requests during pytest"). Written and `py_compile`-clean; imports
`app.services.github_oauth_service`, which pulls in SQLAlchemy/pydantic
via `app.core.config`/`app.models.organization_member`, unavailable in
this sandbox — not pytest-executed here (same bucket as
test_replay_service.py, per DECISIONS.md ADR-036).
"""

import pytest

from app.auth.oauth_state import InMemoryOAuthStateStore
from app.core.config import Settings
from app.domain.exceptions import (
    GitHubAuthorizationDenied,
    GitHubIdentityLookupFailed,
    MalformedGitHubIdentity,
    MissingAuthorizationCode,
    OAuthStateInvalid,
)
from app.github.oauth_models import GitHubIdentity, GitHubTokenResponse
from app.services.github_oauth_service import GitHubOAuthService


class FakeGitHubOAuthClient:
    """Deterministic, in-memory, test-only implementation of
    `GitHubOAuthClient` (mirrors `FakeReplayExecutor`, Phase 7 §9).
    Never wired into production."""

    def __init__(
        self,
        *,
        identity: GitHubIdentity | None = None,
        fail_exchange: bool = False,
        fail_identity: bool = False,
        malformed_identity: bool = False,
    ) -> None:
        self._identity = identity or GitHubIdentity(
            github_user_id=42, github_login="octocat", email="octocat@example.com"
        )
        self._fail_exchange = fail_exchange
        self._fail_identity = fail_identity
        self._malformed_identity = malformed_identity
        self.exchanged_codes: list[str] = []

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://github.com/login/oauth/authorize?state={state}&redirect_uri={redirect_uri}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> GitHubTokenResponse:
        if self._fail_exchange:
            raise GitHubIdentityLookupFailed()  # simulated transport failure
        self.exchanged_codes.append(code)
        return GitHubTokenResponse(
            access_token="gho_fake_token", scope="read:user user:email", token_type="bearer"
        )

    async def fetch_identity(self, *, access_token: str) -> GitHubIdentity:
        if self._fail_identity:
            raise GitHubIdentityLookupFailed()
        if self._malformed_identity:
            raise MalformedGitHubIdentity()
        return self._identity


def _settings() -> Settings:
    return Settings(
        jwt_secret="test-secret",
        github_oauth_client_id="fake-id",
        github_oauth_client_secret="fake-secret",
    )


async def test_start_login_saves_state_and_builds_url(session):
    store = InMemoryOAuthStateStore()
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    start = await service.start_login()
    assert start.state in start.authorization_url
    assert await store.consume(start.state) is True  # was actually saved


async def test_callback_rejects_missing_state(session):
    store = InMemoryOAuthStateStore()
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    with pytest.raises(OAuthStateInvalid):
        await service.handle_callback(code="abc", state=None, error=None)


async def test_callback_rejects_unknown_state(session):
    store = InMemoryOAuthStateStore()
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    with pytest.raises(OAuthStateInvalid):
        await service.handle_callback(code="abc", state="never-issued", error=None)


async def test_callback_rejects_reused_state(session):
    store = InMemoryOAuthStateStore()
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    await store.save("s1", ttl_seconds=60)
    assert await store.consume("s1") is True
    with pytest.raises(OAuthStateInvalid):
        await service.handle_callback(code="abc", state="s1", error=None)


async def test_callback_rejects_github_denial(session):
    store = InMemoryOAuthStateStore()
    await store.save("s1", ttl_seconds=60)
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    with pytest.raises(GitHubAuthorizationDenied):
        await service.handle_callback(code=None, state="s1", error="access_denied")


async def test_callback_rejects_missing_code(session):
    store = InMemoryOAuthStateStore()
    await store.save("s1", ttl_seconds=60)
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    with pytest.raises(MissingAuthorizationCode):
        await service.handle_callback(code=None, state="s1", error=None)


async def test_callback_success_creates_user_and_issues_jwt(session):
    store = InMemoryOAuthStateStore()
    await store.save("s1", ttl_seconds=60)
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=FakeGitHubOAuthClient()
    )
    result = await service.handle_callback(code="abc", state="s1", error=None)
    assert result.email == "octocat@example.com"
    assert result.organization_id is None
    assert result.requires_onboarding is True  # brand-new user, no membership
    assert "gho_" not in result.access_token  # provider token never in the JWT


async def test_callback_second_login_reuses_existing_user(session):
    store = InMemoryOAuthStateStore()
    client = FakeGitHubOAuthClient()
    service = GitHubOAuthService(
        session, settings=_settings(), state_store=store, github_client=client
    )
    await store.save("s1", ttl_seconds=60)
    first = await service.handle_callback(code="abc", state="s1", error=None)

    await store.save("s2", ttl_seconds=60)
    second = await service.handle_callback(code="def", state="s2", error=None)
    assert first.user_id == second.user_id  # matched by github_user_id, not re-created
