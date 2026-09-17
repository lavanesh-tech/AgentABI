"""Rate-limit dependencies (Security Phase D spec §7/§21) — the only
place a route declares "this action is rate-limited." Mirrors
`app/api/deps/authz.py`'s factory-function shape: `rate_limit_by_user`/
`rate_limit_by_client` return a dependency, applied via `dependencies=
[...]` on a route, so no route handler calls Redis directly.
"""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request

from app.api.deps.auth import get_current_user
from app.auth.principal import AuthenticatedPrincipal
from app.core.config import Settings, get_settings
from app.core.rate_limit import RedisRateLimiter, enforce
from app.core.redis import get_redis_client


def get_client_identity(request: Request, settings: Settings) -> str:
    """Derive a rate-limit identity for an unauthenticated request.
    `trusted_proxy_count` (0 by default — see Settings) controls how
    many `X-Forwarded-For` entries, counted from the right, are trusted
    as proxy-added rather than client-supplied; with the default of 0,
    the header is ignored entirely and only the direct TCP peer address
    is used, which is correct for local dev and any deployment with no
    reverse proxy in front of this API, and cannot be spoofed by a
    request header."""

    if settings.trusted_proxy_count > 0:
        # Starlette's `Headers.get` is untyped in this installed version
        # (resolves to `Any`, same root cause as the BaseHTTPMiddleware
        # typing gap documented in app/core/middleware.py) — annotating
        # the local variable narrows it back to `str | None` at the
        # source, rather than letting `Any` leak into `hops`/the return
        # value below.
        forwarded_for: str | None = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
            trusted_index = len(hops) - settings.trusted_proxy_count
            if 0 <= trusted_index < len(hops):
                return hops[trusted_index]
    return request.client.host if request.client else "unknown"


def rate_limit_by_client(
    bucket: str, limit: int, window_seconds: int
) -> Callable[[Request, Settings], Coroutine[Any, Any, None]]:
    """Rate-limits by client IP (spec §5's "anonymous auth endpoint"
    case) — used for the GitHub OAuth login/callback routes, which run
    before any AgentABI identity exists."""

    async def _dependency(
        request: Request,
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> None:
        identity = get_client_identity(request, settings)
        limiter = RedisRateLimiter(get_redis_client(settings))
        await enforce(
            limiter, bucket=bucket, identity=identity, limit=limit, window_seconds=window_seconds
        )

    return _dependency


def rate_limit_by_user(
    bucket: str, limit: int, window_seconds: int
) -> Callable[[AuthenticatedPrincipal, Settings], Coroutine[Any, Any, None]]:
    """Rate-limits by authenticated user id (spec §5's "authenticated
    endpoint" case) — used for mutation/scan/replay routes, which
    already depend on `get_current_user` via authorization, so this
    adds no extra authentication cost (FastAPI resolves a given
    dependency once per request)."""

    async def _dependency(
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> None:
        limiter = RedisRateLimiter(get_redis_client(settings))
        await enforce(
            limiter,
            bucket=bucket,
            identity=str(principal.user_id),
            limit=limit,
            window_seconds=window_seconds,
        )

    return _dependency
