"""Typed results for the GitHub OAuth2 client (Security Phase B spec
§13). Nothing downstream of `GitHubOAuthClient` ever touches a raw
`httpx.Response`/`dict` from GitHub — these dataclasses are the only
shape provider data takes past this module.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GitHubTokenResponse:
    """The token-exchange result. `access_token` is the GitHub OAuth
    access token — never persisted, never logged, never returned to a
    client (spec §12); it exists only for the duration of the identity
    lookup that immediately follows."""

    access_token: str
    scope: str
    token_type: str


@dataclass(frozen=True)
class GitHubIdentity:
    """A verified GitHub identity. `github_user_id` is GitHub's
    immutable numeric user id — the stable identity key (spec §8);
    `github_login` is the current username, informational only and
    never used as a lookup key since it can change."""

    github_user_id: int
    github_login: str
    email: str


class GitHubOAuthClient(Protocol):
    """The abstraction `GitHubOAuthService` depends on. Kept in this
    module (not `oauth_client.py`, which imports `httpx`) so the service
    and its tests can import the Protocol without pulling in `httpx` —
    unavailable in this sandbox (same restriction as every prior
    phase's deps). `HttpxGitHubOAuthClient` (production) and
    `FakeGitHubOAuthClient` (tests) both implement this structurally."""

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> GitHubTokenResponse: ...

    async def fetch_identity(self, *, access_token: str) -> GitHubIdentity: ...
