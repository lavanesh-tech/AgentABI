"""Authentication API. `/me` (Security Phase A) proves that a valid
AgentABI JWT resolves to a real, active user. `/github/login` and
`/github/callback` (Security Phase B) are the OAuth2 login flow itself —
GitHub authenticates the person; AgentABI JWT issuance at the end of the
callback is the only thing routes elsewhere ever check.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.github_oauth import get_github_oauth_service
from app.api.deps.rate_limit import rate_limit_by_client
from app.auth.principal import AuthenticatedPrincipal
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.organization_member import OrganizationRole
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.services.github_oauth_service import GitHubCallbackResult, GitHubOAuthService

router = APIRouter(prefix="/auth", tags=["auth"])

_settings = get_settings()
# By client IP/identity (spec §5) — these run before any AgentABI user
# identity exists, so there is no user_id to key on yet.
_RATE_AUTH = Depends(
    rate_limit_by_client(
        "auth", _settings.rate_limit_auth_requests, _settings.rate_limit_auth_window_seconds
    )
)


class AuthMeResponse(BaseModel):
    """Explicit response model, never the ORM `User`/`OrganizationMember`
    — there is no field on this model capable of serializing a secret,
    unlike the underlying rows (Phase A spec §13)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None
    role: OrganizationRole | None
    requires_onboarding: bool

    @classmethod
    def from_principal(
        cls, principal: AuthenticatedPrincipal, *, requires_onboarding: bool
    ) -> "AuthMeResponse":
        return cls(
            user_id=principal.user_id,
            email=principal.email,
            organization_id=principal.organization_id,
            role=principal.role,
            requires_onboarding=requires_onboarding,
        )


@router.get(
    "/me",
    response_model=AuthMeResponse,
    summary="Get the authenticated user",
    description="Requires a Bearer AgentABI JWT. Returns the caller's identity, "
    "if the token carries organization context their role in it, and a freshly "
    "computed `requires_onboarding` flag (true only when the caller currently has "
    "zero organization memberships). This is deliberately recomputed from the "
    "database on every call — unlike the one-time `requires_onboarding` returned "
    "by the GitHub OAuth callback, an already-authenticated session (e.g. one "
    "that predates onboarding being implemented) can use this to discover it "
    "still needs to onboard without a fresh login.",
)
async def get_me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthMeResponse:
    memberships = await OrganizationMemberRepository(session).list_for_user(principal.user_id)
    return AuthMeResponse.from_principal(principal, requires_onboarding=len(memberships) == 0)


class GitHubCallbackResponse(BaseModel):
    """Explicit response model for a successful callback. Carries the
    AgentABI JWT (`access_token`) only — never the GitHub OAuth access
    token, never a client secret (spec §13/§20)."""

    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None
    role: OrganizationRole | None
    requires_onboarding: bool

    @classmethod
    def from_result(cls, result: GitHubCallbackResult) -> "GitHubCallbackResponse":
        return cls(
            access_token=result.access_token,
            user_id=result.user_id,
            email=result.email,
            organization_id=result.organization_id,
            role=result.role,
            requires_onboarding=result.requires_onboarding,
        )


@router.get(
    "/github/login",
    dependencies=[_RATE_AUTH],
    summary="Start GitHub OAuth2 login",
    description="Public, no AgentABI JWT required. Redirects the browser to GitHub's "
    "authorization page; not directly callable from an API client like Postman.",
)
async def github_login(
    service: Annotated[GitHubOAuthService, Depends(get_github_oauth_service)],
) -> RedirectResponse:
    start = await service.start_login()
    return RedirectResponse(url=start.authorization_url, status_code=302)


@router.get(
    "/github/callback",
    response_model=GitHubCallbackResponse,
    dependencies=[_RATE_AUTH],
    summary="GitHub OAuth2 callback",
    description="Public, no AgentABI JWT required — GitHub redirects here after login. "
    "Returns the AgentABI JWT to use as the Bearer token on every other endpoint.",
)
async def github_callback(
    service: Annotated[GitHubOAuthService, Depends(get_github_oauth_service)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> GitHubCallbackResponse:
    result = await service.handle_callback(code=code, state=state, error=error)
    return GitHubCallbackResponse.from_result(result)
