"""HTTP request metrics middleware (Phase 16 spec §6). Records
`agentabi_http_requests_total`, `agentabi_http_request_duration_seconds`,
and `agentabi_http_requests_in_progress` for every request, labeled only
by method, normalized route template, and status code — never the raw
path, query string, or any path parameter value (spec §22's cardinality
rule), which is why this reads `request.scope["route"].path` (the
Starlette route *template*, e.g. "/api/v1/projects/{project_id}") rather
than `request.url.path`.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings
from app.observability import metrics

_UNMATCHED_ROUTE = "unmatched"


def _route_template(request: Request) -> str:
    """Starlette sets `scope["route"]` once routing has matched a
    handler; a request that 404s (no route matched) never gets one — we
    fall back to a single bounded label rather than the raw path, which
    would be unbounded cardinality for anyone probing random URLs."""

    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else _UNMATCHED_ROUTE


def _resolve_route_template(app: ASGIApp, scope: Scope) -> str:
    """Resolve the matched route template without using the raw URL path."""
    current: Any = app
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        routes = getattr(current, "routes", None)
        if routes is not None:
            for route in routes:
                match, _ = route.matches(scope)
                if match == Match.FULL:
                    path = getattr(route, "path", None)
                    if isinstance(path, str):
                        return path
            return _UNMATCHED_ROUTE

        current = getattr(current, "app", None)

    return _UNMATCHED_ROUTE


# See app/core/security_headers.py's comment: Starlette's
# `BaseHTTPMiddleware` resolves to `Any` under this project's mypy
# configuration, so strict mode's `disallow_subclassing_any` flags
# subclassing it — a genuine third-party typing gap with no cleaner
# typed boundary available.
class PrometheusMetricsMiddleware:
    """Pure ASGI metrics middleware.

    Using pure ASGI instead of BaseHTTPMiddleware lets the downstream
    Starlette/FastAPI router mutate the shared ASGI scope with the matched
    route template. After the request completes we can therefore record
    the bounded route pattern rather than the raw path.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._settings.metrics_enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        start = time.monotonic()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        with metrics.track_http_in_progress(self._settings, method=method):
            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                request = Request(scope)
                route = _route_template(request)
                if route == _UNMATCHED_ROUTE:
                    route = _resolve_route_template(self.app, scope)
                duration = time.monotonic() - start
                metrics.record_http_request(
                    self._settings,
                    method=method,
                    route=route,
                    status=str(status_code),
                    duration_seconds=duration,
                )


__all__ = ["PrometheusMetricsMiddleware"]
