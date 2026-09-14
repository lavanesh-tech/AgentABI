"""Authentication dependencies — the one place a Bearer token becomes a
typed `AuthenticatedPrincipal` (Phase A spec §6/§7). Route handlers
depend on `get_current_user`; nothing else in the application decodes a
JWT or trusts a claim directly.

`HTTPBearer(auto_error=False)` (rather than FastAPI's default
`auto_error=True`) is what makes the missing-token case raise our own
`AuthenticationRequired` — mapped centrally like every other domain
error (`app/api/v1/errors.py`) — instead of a raw `HTTPException` that
bypasses that mapping. It also registers a Bearer `SecurityScheme` with
FastAPI's OpenAPI generation, so `/docs` shows the lock icon and
"Authorize" flow on every endpoint that depends on this (Phase A §9).
"""

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token
from app.auth.principal import AuthenticatedPrincipal
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.domain.exceptions import AuthenticationRequired, DisabledUser, InvalidToken, UnknownUser
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.user_repository import UserRepository

_bearer_scheme = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description="AgentABI JWT access token (obtained via GitHub OAuth2 login).",
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthenticatedPrincipal:
    """Resolve the request's Bearer token into an
    `AuthenticatedPrincipal`. Fails securely at every step (Phase A
    spec §6):

    1. No/malformed `Authorization` header -> `AuthenticationRequired`.
    2. JWT decode/signature/issuer/audience/claim checks -> `InvalidToken`/
       `ExpiredToken` (raised by `app.auth.jwt.decode_token`).
    3. `sub` doesn't resolve to a real user -> `UnknownUser`. A valid
       signature is never, by itself, treated as proof of a live
       identity.
    4. User exists but `is_active` is false -> `DisabledUser`.

    The user's role is *not* read from the token — it's reloaded from
    `OrganizationMember` for the token's `org_id`, so a permission
    change made after the token was issued takes effect immediately
    (see `app/auth/claims.py`). A token with no `org_id` (or one the
    user no longer belongs to) simply yields `role=None`; Security
    Phase C's authorization layer decides what that means per endpoint.
    """

    if credentials is None or not credentials.credentials:
        raise AuthenticationRequired()

    try:
        claims = decode_token(
            credentials.credentials,
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except ValueError as exc:
        # decode_token only ever raises InvalidToken/ExpiredToken
        # (both AgentABIError subclasses), but this guards against a
        # stray stdlib exception ever reaching the client as a 500 with
        # internal detail (Phase A spec §10).
        raise InvalidToken() from exc

    try:
        user_id = _parse_uuid(claims.sub)
    except ValueError as exc:
        raise InvalidToken("token subject is not a valid user id") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise UnknownUser()
    if not user.is_active:
        raise DisabledUser()

    organization_id = None
    role = None
    if claims.org_id is not None:
        try:
            organization_id = _parse_uuid(claims.org_id)
        except ValueError:
            organization_id = None
        if organization_id is not None:
            membership = await OrganizationMemberRepository(session).get_for_user_and_organization(
                user.id, organization_id
            )
            role = membership.role if membership is not None else None

    return AuthenticatedPrincipal(
        user_id=user.id, email=user.email, organization_id=organization_id, role=role
    )


def _parse_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


# Alias matching the spec's naming (§6) — identical dependency, kept as
# a separate name so route signatures can express intent ("this route
# just needs *someone* authenticated" vs. a future Phase C dependency
# that also enforces a role/project scope).
require_authenticated_user = get_current_user
