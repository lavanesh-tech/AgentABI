"""Organization onboarding API. `POST /organizations` is the only route
here (task: "Implement the missing first-organization / first-OWNER
onboarding flow discovered during local product verification"): it
closes the gap where org-scoped routes (`/organizations/{id}/projects`,
`app/api/deps/authz.py`) all require an existing organization, but
nothing previously let an authenticated, orgless user create the first
one. Not a general organization-management API — see
`app/services/organization_service.py`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.api.deps.rate_limit import rate_limit_by_user
from app.auth.jwt import encode_token
from app.auth.principal import AuthenticatedPrincipal
from app.core.config import get_settings
from app.core.database import get_db_session
from app.models.organization_member import OrganizationRole
from app.services.organization_service import OnboardingResult, OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])

_settings = get_settings()
# Authenticated-user-keyed (spec: "Apply an appropriate existing or
# narrowly-scoped onboarding rate limit") — reuses `get_current_user`,
# which this route already depends on for authentication, at no extra
# cost.
_RATE_ONBOARDING = Depends(
    rate_limit_by_user(
        "onboarding",
        _settings.rate_limit_onboarding_requests,
        _settings.rate_limit_onboarding_window_seconds,
    )
)


class OrganizationCreateRequest(BaseModel):
    """Deliberately the *only* accepted shape: `extra="forbid"` means any
    extra field (an owner user id, a role, an organization id, arbitrary
    membership data) is rejected with a 422 rather than silently
    ignored. Identity for the new OWNER membership comes exclusively
    from the authenticated principal, never from this body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class OrganizationOnboardingResponse(BaseModel):
    """A fresh AgentABI JWT is issued here because the token used to
    call this endpoint was necessarily minted before this organization
    existed (it had no `org_id` to carry, per ADR-040 — a caller with
    zero memberships always gets `organization_id=None`). The frontend
    swaps to this token so it can immediately act with organization
    context, exactly like `GitHubCallbackResponse.access_token` today.
    The token still carries no `role` claim — authorization continues
    to reload role from `OrganizationMember` on every request (see
    `app/api/deps/auth.py`), so this token grants no privilege by
    itself."""

    access_token: str
    token_type: str = "bearer"
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: OrganizationRole

    @classmethod
    def from_result(
        cls, result: OnboardingResult, *, access_token: str
    ) -> "OrganizationOnboardingResponse":
        return cls(
            access_token=access_token,
            organization_id=result.organization.id,
            organization_name=result.organization.name,
            organization_slug=result.organization.slug,
            role=result.membership.role,
        )


def get_organization_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OrganizationService:
    return OrganizationService(session)


ServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]


@router.post(
    "",
    response_model=OrganizationOnboardingResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_RATE_ONBOARDING],
    summary="Create your first organization",
    description=(
        "Authenticated self-service onboarding. Requires a valid AgentABI JWT "
        "and that the caller currently has zero organization memberships — "
        "reloaded from the database on every call, never trusted from the "
        "token or the request body. On success the caller becomes OWNER of a "
        "newly created organization and receives a fresh AgentABI JWT carrying "
        "the new organization context. Already belonging to an organization "
        "returns 409 Conflict; this endpoint never adds the caller to an "
        "existing organization and never accepts a role, organization id, or "
        "another user's id in the request body."
    ),
)
async def create_first_organization(
    payload: OrganizationCreateRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
    service: ServiceDep,
) -> OrganizationOnboardingResponse:
    result = await service.onboard_first_organization(
        user_id=principal.user_id,
        name=payload.name,
        request_id=request.headers.get("x-request-id"),
    )

    access_token = encode_token(
        subject=str(principal.user_id),
        secret=_settings.jwt_secret,
        algorithm=_settings.jwt_algorithm,
        issuer=_settings.jwt_issuer,
        audience=_settings.jwt_audience,
        expires_in_seconds=_settings.jwt_access_token_expire_minutes * 60,
        organization_id=str(result.organization.id),
    )
    return OrganizationOnboardingResponse.from_result(result, access_token=access_token)
