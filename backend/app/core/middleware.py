"""Request-scoped middleware: correlation IDs for tracing a request through
logs (and, in a later observability phase, through OpenTelemetry spans)."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_correlation_id, clear_contextvars

CORRELATION_ID_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Reads/generates a correlation ID per request, binds it to structlog's
    contextvars so every log line emitted while handling the request
    includes it, and echoes it back on the response header."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = request.headers.get(CORRELATION_ID_HEADER, str(uuid.uuid4()))
        bind_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            clear_contextvars()
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
