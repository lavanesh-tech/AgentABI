"""GitHub OAuth2 client (Security Phase B spec §4). The only module that
speaks HTTP to GitHub for login purposes — API routes and the
orchestrating service never construct a GitHub URL or call `httpx`
directly.

Scopes requested: `read:user user:email` — the minimum needed to
authenticate the person and resolve a usable email address. No
repository scopes (`repo`, `admin:org`, ...) are requested in Phase B;
this is a login flow, not a GitHub API integration (spec §6).

`redis`/`httpx` are declared dependencies (pyproject.toml) but not
installable in this sandbox (same PyPI-403 restriction as every prior
phase), so this module is written and `py_compile`-clean but not
exercised by `pytest` here — orchestration logic that depends on it
(`app/services/github_oauth_service.py`) is tested against
`FakeGitHubOAuthClient` instead (spec §15).
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.domain.exceptions import (
    GitHubIdentityLookupFailed,
    GitHubTokenExchangeFailed,
    MalformedGitHubIdentity,
)
from app.github.oauth_models import GitHubIdentity, GitHubTokenResponse
from app.observability import start_span

# `GitHubOAuthClient` (the Protocol) lives in `oauth_models.py`, not
# here — see that module's docstring on why.

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_API_URL = "https://api.github.com/user"
EMAILS_API_URL = "https://api.github.com/user/emails"

# Minimal scopes: identity + email only (spec §6). No repository access.
OAUTH_SCOPES = "read:user user:email"


@dataclass(frozen=True)
class HttpxGitHubOAuthClient:
    """Production implementation. `client_id`/`client_secret` come from
    `Settings` (never hardcoded, never logged — spec §3)."""

    client_id: str
    client_secret: str

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "scope": OAUTH_SCOPES,
                "state": state,
                "allow_signup": "true",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> GitHubTokenResponse:
        # Never a code/token/secret attribute on this span — spec
        # §20/§33: only the operation itself is observable.
        with start_span("github.oauth.exchange", kind="client"):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        TOKEN_URL,
                        headers={"Accept": "application/json"},
                        data={
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "code": code,
                            "redirect_uri": redirect_uri,
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                # Never surface the upstream body/status to the caller — it
                # can echo back request parameters. See spec §14.
                raise GitHubTokenExchangeFailed() from exc

            access_token = body.get("access_token")
            token_type = body.get("token_type")
            scope = body.get("scope", "")
            if (
                not isinstance(access_token, str)
                or not access_token
                or not isinstance(token_type, str)
            ):
                raise GitHubTokenExchangeFailed()
            return GitHubTokenResponse(
                access_token=access_token, scope=scope, token_type=token_type
            )

    async def fetch_identity(self, *, access_token: str) -> GitHubIdentity:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                user_response = await client.get(USER_API_URL, headers=headers)
                user_response.raise_for_status()
                user_body = user_response.json()

                email = user_body.get("email")
                if not email:
                    emails_response = await client.get(EMAILS_API_URL, headers=headers)
                    emails_response.raise_for_status()
                    email = _select_primary_verified_email(emails_response.json())
        except httpx.HTTPError as exc:
            raise GitHubIdentityLookupFailed() from exc
        except ValueError as exc:  # non-JSON body
            raise MalformedGitHubIdentity() from exc

        github_user_id = user_body.get("id")
        github_login = user_body.get("login")
        if not isinstance(github_user_id, int) or not isinstance(github_login, str):
            raise MalformedGitHubIdentity("GitHub user response is missing id/login")
        if not email:
            # Never fabricate a placeholder address (spec §9).
            raise MalformedGitHubIdentity(
                "GitHub account has no public or verified email available"
            )

        return GitHubIdentity(github_user_id=github_user_id, github_login=github_login, email=email)


def _select_primary_verified_email(entries: object) -> str | None:
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if (
            isinstance(entry, dict)
            and entry.get("primary") is True
            and entry.get("verified") is True
            and isinstance(entry.get("email"), str)
        ):
            return entry["email"]
    return None
