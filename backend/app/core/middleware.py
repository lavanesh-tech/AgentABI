"""Request-scoped middleware: correlation IDs for tracing a request through
logs (and, in a later observability phase, through OpenTelemetry spans)."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_correlation_id, clear_contextvars

CORRELATION_ID_HEADER = "X-Correlation-ID"


# See app/core/security_headers.py's comment: Starlette's
# `BaseHTTPMiddleware` resolves to `Any` under this project's mypy
# configuration, so strict mode's `disallow_subclassing_any` flags
# subclassing it — a genuine third-party typing gap with no cleaner
# typed boundary available.
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Reads/generates a correlation ID per request, binds it to structlog's
    contextvars so every log line emitted while handling the request
    includes it, and echoes it back on the response header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER, str(uuid.uuid4()))
        # Set on request.state (not just structlog's contextvars) so the
        # exception handlers in app/api/v1/errors.py can read it directly —
        # they run inside call_next(), so contextvars would technically
        # still be bound at that point too, but request.state is the more
        # explicit, harness-independent source of truth (Security Phase D).
        request.state.correlation_id = correlation_id
        bind_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            clear_contextvars()
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
