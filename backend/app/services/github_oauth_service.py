"""GitHubOAuthService — orchestrates the login/callback flow (Security
Phase B spec §2). The one place that sequences state validation, code
exchange, identity lookup, user/membership resolution, and AgentABI JWT
issuance; API routes call this and never touch `GitHubOAuthClient` or
`OAuthStateStore` directly (mirrors `ReplayService`, Phase 7 §11).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import encode_token
from app.auth.oauth_state import OAuthStateStore, generate_state
from app.core.config import Settings
from app.domain.exceptions import (
    GitHubAuthorizationDenied,
    MissingAuthorizationCode,
    OAuthStateInvalid,
)
from app.github.oauth_models import GitHubOAuthClient
from app.models.organization_member import OrganizationRole
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class GitHubLoginStart:
    authorization_url: str
    state: str


@dataclass(frozen=True)
class GitHubCallbackResult:
    """Everything the callback endpoint needs to respond with. Never
    carries the GitHub access token (spec §12) — only the AgentABI JWT
    (`access_token`) and the same public fields `/auth/me` exposes."""

    access_token: str
    user_id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None
    role: OrganizationRole | None
    requires_onboarding: bool


class GitHubOAuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        state_store: OAuthStateStore,
        github_client: GitHubOAuthClient,
    ) -> None:
        self._session = session
        self._settings = settings
        self._state_store = state_store
        self._github_client = github_client
        self._users = UserRepository(session)
        self._memberships = OrganizationMemberRepository(session)

    async def start_login(self) -> GitHubLoginStart:
        state = generate_state()
        await self._state_store.save(
            state, ttl_seconds=self._settings.github_oauth_state_ttl_seconds
        )
        url = self._github_client.build_authorization_url(
            state=state, redirect_uri=self._settings.github_oauth_redirect_uri
        )
        return GitHubLoginStart(authorization_url=url, state=state)

    async def handle_callback(
        self, *, code: str | None, state: str | None, error: str | None
    ) -> GitHubCallbackResult:
        # Order matters (spec §7): validate + consume state *before*
        # trusting anything else about the callback, including a
        # `error` field GitHub itself sent — an attacker replaying an
        # old callback URL must not get a different, more informative
        # failure than someone who guessed a state value.
        if not state or not await self._state_store.consume(state):
            raise OAuthStateInvalid()

        if error:
            raise GitHubAuthorizationDenied()
        if not code:
            raise MissingAuthorizationCode()

        token = await self._github_client.exchange_code(
            code=code, redirect_uri=self._settings.github_oauth_redirect_uri
        )
        identity = await self._github_client.fetch_identity(access_token=token.access_token)
        # `token.access_token` is not referenced again — discarded here,
        # never persisted, never logged, never returned (spec §12).

        user = await self._users.get_by_github_id(identity.github_user_id)
        if user is None:
            user = await self._users.create_from_github(
                email=identity.email,
                github_user_id=identity.github_user_id,
                github_login=identity.github_login,
            )
            await self._session.commit()

        memberships = await self._memberships.list_for_user(user.id)
        organization_id: uuid.UUID | None = None
        role: OrganizationRole | None = None
        # Exactly one membership -> attach that org context to the JWT.
        # Zero or multiple memberships both yield organization_id=None:
        # zero because there is nothing to grant, many because picking
        # one automatically would be an arbitrary, undocumented
        # privilege choice (spec §10 — no automatic org join, no
        # silently-granted admin/owner). Org selection for multi-org
        # users is a later-phase (onboarding/org-switch) concern.
        if len(memberships) == 1:
            organization_id = memberships[0].organization_id
            role = memberships[0].role

        access_token = encode_token(
            subject=str(user.id),
            secret=self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
            issuer=self._settings.jwt_issuer,
            audience=self._settings.jwt_audience,
            expires_in_seconds=self._settings.jwt_access_token_expire_minutes * 60,
            organization_id=str(organization_id) if organization_id else None,
        )

        return GitHubCallbackResult(
            access_token=access_token,
            user_id=user.id,
            email=user.email,
            organization_id=organization_id,
            role=role,
            requires_onboarding=len(memberships) == 0,
        )
