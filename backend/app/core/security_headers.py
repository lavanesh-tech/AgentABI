"""Security response headers (Security Phase D spec §12/§13/§17).

Deliberately does NOT set `Content-Security-Policy`: this is a JSON API
whose own `/docs` (Swagger UI) loads its assets from a CDN, so a CSP
strict enough to be meaningful here would break Swagger. CSP ownership is
documented (docs/ARCHITECTURE.md) as belonging to the frontend/reverse-
proxy layer instead, not this API.

`Strict-Transport-Security` is emitted only when `settings.is_production`
— never in local HTTP development, where a browser that cached an HSTS
header would then refuse plain-HTTP `localhost` for its max-age window.
In this deployment the API terminates behind an ALB in production
(docs/ARCHITECTURE.md), so sending HSTS from the app itself (rather than
relying solely on the ALB) is a deliberate belt-and-braces choice, not a
duplication.

`Cache-Control: no-store` is added only to auth-prefixed paths — the
JWT-issuing callback and `/auth/me` responses must never be cached by an
intermediary — not globally, since most responses have no reason to
forbid caching.
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import Settings


# Starlette's `BaseHTTPMiddleware` itself resolves to `Any` under this
# project's mypy configuration (a known Starlette typing gap — see
# app/core/middleware.py's identical note), so strict mode's
# `disallow_subclassing_any` flags subclassing it here. There is no
# cleaner typed boundary: this is Starlette's own, real, prescribed
# middleware base class.
class SecurityHeadersMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if self._settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        if request.url.path.startswith(f"{self._settings.api_v1_prefix}/auth"):
            response.headers["Cache-Control"] = "no-store"
        return response
