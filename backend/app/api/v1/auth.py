"""Authentication API — Security Phase A's protected-endpoint proof
(spec §8). GitHub OAuth login/callback is Security Phase B; this router
only proves that a valid AgentABI JWT resolves to a real, active user.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.deps.auth import get_current_user
from app.auth.principal import AuthenticatedPrincipal
from app.models.organization_member import OrganizationRole

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthMeResponse(BaseModel):
    """Explicit response model, never the ORM `User`/`OrganizationMember`
    — there is no field on this model capable of serializing a secret,
    unlike the underlying rows (Phase A spec §13)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None
    role: OrganizationRole | None

    @classmethod
    def from_principal(cls, principal: AuthenticatedPrincipal) -> "AuthMeResponse":
        return cls(
            user_id=principal.user_id,
            email=principal.email,
            organization_id=principal.organization_id,
            role=principal.role,
        )


@router.get("/me", response_model=AuthMeResponse)
async def get_me(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
) -> AuthMeResponse:
    return AuthMeResponse.from_principal(principal)
