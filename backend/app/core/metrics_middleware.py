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

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import Settings
from app.observability import record_http_request, track_http_in_progress

_UNMATCHED_ROUTE = "unmatched"


def _route_template(request: Request) -> str:
    """Starlette sets `scope["route"]` once routing has matched a
    handler; a request that 404s (no route matched) never gets one — we
    fall back to a single bounded label rather than the raw path, which
    would be unbounded cardinality for anyone probing random URLs."""

    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if isinstance(path, str) else _UNMATCHED_ROUTE


class PrometheusMetricsMiddleware(BaseHTTPMiddleware):
    """Outermost middleware layer (added last in `create_app()`) so its
    timing covers the full request/response cycle, including every other
    middleware. A no-op pass-through when `METRICS_ENABLED=false` —
    metrics recording itself never raises (spec §24)."""

    def __init__(self, app, settings: Settings) -> None:  # noqa: ANN001 - Starlette app type
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self._settings.metrics_enabled:
            return await call_next(request)

        method = request.method
        start = time.monotonic()
        status_code = 500
        # Route isn't known until routing has run inside call_next(), so
        # the in-progress gauge is labeled by method only up front and
        # the final counter/histogram use the resolved route afterward.
        with track_http_in_progress(self._settings, method=method):
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            finally:
                route = _route_template(request)
                duration = time.monotonic() - start
                record_http_request(
                    self._settings,
                    method=method,
                    route=route,
                    status=str(status_code),
                    duration_seconds=duration,
                )


__all__ = ["PrometheusMetricsMiddleware"]
