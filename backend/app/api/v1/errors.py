"""Central mapping from domain exceptions to HTTP responses.

Registered once on the FastAPI app (see `app/main.py`) so no route handler
needs its own try/except around a service call. Starlette resolves the
handler by walking the exception's MRO, so a leaf exception like
`DuplicateComponent` (a `ConflictError`) is caught by the `ConflictError`
handler without needing its own registration.

Security Phase D §11/§14 standardizes every error response (domain
errors, FastAPI/Pydantic validation errors, and unhandled exceptions)
into one envelope: `{"error": {"code": ..., "message": ..., "request_id":
...}}`. `request_id` is the correlation id set on `request.state` by
`CorrelationIdMiddleware` — never absent, since that middleware runs on
every request before routing.
"""

import uuid

import structlog
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.domain.exceptions import (
    AgentABIError,
    AuthenticationError,
    AuthenticationRequired,
    ConflictError,
    ExpiredToken,
    GitHubAuthorizationDenied,
    GitHubIdentityLookupFailed,
    GitHubOAuthNotConfigured,
    GitHubTokenExchangeFailed,
    GitHubWebhookNotConfigured,
    GraphUnavailable,
    InvalidCompatibilityComparison,
    InvalidComponentContent,
    InvalidDependencyRelationship,
    InvalidReplaySubstitution,
    InvalidTrajectoryEvent,
    MalformedGitHubIdentity,
    MissingAuthorizationCode,
    MissingWebhookDeliveryId,
    NotFoundError,
    OAuthStateInvalid,
    OAuthStateStoreUnavailable,
    OrganizationAccessDenied,
    PermissionDenied,
    ProjectAccessDenied,
    RateLimited,
    RateLimiterUnavailable,
    ReplayExecutionFailed,
    ReplayExecutorUnavailable,
    SchemaNormalizationError,
    TrajectoryPayloadTooLarge,
    UnsupportedCompatibilityType,
    WebhookSignatureError,
)

logger = structlog.get_logger(__name__)

# --- Standardized error codes (spec §11) -----------------------------------
VALIDATION_ERROR = "VALIDATION_ERROR"
AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
INVALID_TOKEN = "INVALID_TOKEN"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
RATE_LIMITED = "RATE_LIMITED"
CONFLICT = "CONFLICT"
REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
INTERNAL_ERROR = "INTERNAL_ERROR"
SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
INVALID_REQUEST = "INVALID_REQUEST"
UPSTREAM_ERROR = "UPSTREAM_ERROR"
INVALID_WEBHOOK_SIGNATURE = "INVALID_WEBHOOK_SIGNATURE"

# Domain exception class -> (status_code, error_code). Order doesn't matter
# for dispatch (FastAPI/Starlette pick the most specific registered
# handler by MRO) but each entry here becomes its own @app.exception_handler
# below, so every leaf exception not listed explicitly still resolves to
# its nearest listed base class (e.g. DuplicateComponent -> ConflictError).
_DOMAIN_ERROR_MAP: dict[type[Exception], tuple[int, str]] = {
    NotFoundError: (status.HTTP_404_NOT_FOUND, RESOURCE_NOT_FOUND),
    ConflictError: (status.HTTP_409_CONFLICT, CONFLICT),
    InvalidComponentContent: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    InvalidDependencyRelationship: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    GraphUnavailable: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    InvalidCompatibilityComparison: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    UnsupportedCompatibilityType: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    SchemaNormalizationError: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    InvalidTrajectoryEvent: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    TrajectoryPayloadTooLarge: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    InvalidReplaySubstitution: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    ReplayExecutorUnavailable: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    ReplayExecutionFailed: (status.HTTP_422_UNPROCESSABLE_ENTITY, VALIDATION_ERROR),
    OAuthStateInvalid: (status.HTTP_401_UNAUTHORIZED, INVALID_TOKEN),
    GitHubAuthorizationDenied: (status.HTTP_401_UNAUTHORIZED, INVALID_TOKEN),
    MissingAuthorizationCode: (status.HTTP_400_BAD_REQUEST, INVALID_REQUEST),
    GitHubTokenExchangeFailed: (status.HTTP_502_BAD_GATEWAY, UPSTREAM_ERROR),
    GitHubIdentityLookupFailed: (status.HTTP_502_BAD_GATEWAY, UPSTREAM_ERROR),
    MalformedGitHubIdentity: (status.HTTP_502_BAD_GATEWAY, UPSTREAM_ERROR),
    OAuthStateStoreUnavailable: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    GitHubOAuthNotConfigured: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    PermissionDenied: (status.HTTP_403_FORBIDDEN, AUTHORIZATION_DENIED),
    OrganizationAccessDenied: (status.HTTP_404_NOT_FOUND, RESOURCE_NOT_FOUND),
    ProjectAccessDenied: (status.HTTP_404_NOT_FOUND, RESOURCE_NOT_FOUND),
    RateLimiterUnavailable: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    WebhookSignatureError: (status.HTTP_401_UNAUTHORIZED, INVALID_WEBHOOK_SIGNATURE),
    GitHubWebhookNotConfigured: (status.HTTP_503_SERVICE_UNAVAILABLE, SERVICE_UNAVAILABLE),
    MissingWebhookDeliveryId: (status.HTTP_400_BAD_REQUEST, INVALID_REQUEST),
    AgentABIError: (status.HTTP_400_BAD_REQUEST, INVALID_REQUEST),
}


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorEnvelope(BaseModel):
    """The typed shape of every error response this API returns
    (Security Phase D). Used only for OpenAPI documentation (spec §6/
    Phase F §6) — the actual response is still built by `_envelope()`
    below, never rendered through this model at runtime."""

    error: ErrorDetail


# Attached to router `responses=` (spec §6/Phase F §5) so Swagger shows
# the standardized envelope for common failure statuses without
# repeating a `responses={...}` dict on every individual route.
COMMON_ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: {"model": ErrorEnvelope, "description": "Invalid request"},
    401: {"model": ErrorEnvelope, "description": "Authentication required or invalid"},
    403: {"model": ErrorEnvelope, "description": "Authorization denied"},
    404: {"model": ErrorEnvelope, "description": "Resource not found"},
    409: {"model": ErrorEnvelope, "description": "Conflict with existing state"},
    413: {"model": ErrorEnvelope, "description": "Request body too large"},
    422: {"model": ErrorEnvelope, "description": "Validation error"},
    429: {"model": ErrorEnvelope, "description": "Rate limit exceeded"},
    500: {"model": ErrorEnvelope, "description": "Internal server error"},
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", None) or str(uuid.uuid4())


def _envelope(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    def _make_handler(status_code: int, code: str):
        async def _handler(request: Request, exc: Exception) -> JSONResponse:
            return _envelope(status_code, code, str(exc), _request_id(request))

        return _handler

    for exc_class, (status_code, code) in _DOMAIN_ERROR_MAP.items():
        app.add_exception_handler(exc_class, _make_handler(status_code, code))

    @app.exception_handler(AuthenticationError)
    async def handle_authentication_error(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        # One handler for every authentication failure mode
        # (AuthenticationRequired/InvalidToken/ExpiredToken/UnknownUser/
        # DisabledUser) — see docs/DECISIONS.md on why these don't get
        # distinguishable HTTP responses. A WWW-Authenticate header is
        # the standard signal that a bearer-token challenge is expected
        # (RFC 6750).
        if isinstance(exc, ExpiredToken):
            code = TOKEN_EXPIRED
        elif isinstance(exc, AuthenticationRequired):
            code = AUTHENTICATION_REQUIRED
        else:
            code = INVALID_TOKEN
        response = _envelope(status.HTTP_401_UNAUTHORIZED, code, str(exc), _request_id(request))
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(RateLimited)
    async def handle_rate_limited(request: Request, exc: RateLimited) -> JSONResponse:
        response = _envelope(
            status.HTTP_429_TOO_MANY_REQUESTS, RATE_LIMITED, str(exc), _request_id(request)
        )
        response.headers["Retry-After"] = str(exc.retry_after_seconds)
        return response

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI/Pydantic's default `errors()` includes an `input` key
        # echoing the raw submitted value back — that can be an
        # oversized body, or (worse) a secret the caller mistakenly put
        # in a field. Keep only location/message/type: enough for a
        # caller to fix their request, nothing echoed back.
        safe_errors = [
            {
                "location": list(error.get("loc", [])),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        request_id = _request_id(request)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": VALIDATION_ERROR,
                    "message": "Request validation failed",
                    "request_id": request_id,
                    "fields": safe_errors,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Full detail (type, message, traceback via exc_info) goes only to
        # the server-side structured logger — secrets already flow through
        # this logger's existing redaction path elsewhere in the app.
        # Never: traceback, SQL text, Redis error text, JWT internals,
        # OAuth provider payloads, or environment values reach the client.
        request_id = _request_id(request)
        logger.exception(
            "unhandled_exception",
            request_id=request_id,
            path=request.url.path,
            exc_type=type(exc).__name__,
        )
        return _envelope(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            INTERNAL_ERROR,
            "An internal error occurred",
            request_id,
        )
