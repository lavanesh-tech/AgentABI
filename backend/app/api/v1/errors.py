"""Central mapping from domain exceptions to HTTP responses.

Registered once on the FastAPI app (see `app/main.py`) so no route handler
needs its own try/except around a service call. Starlette resolves the
handler by walking the exception's MRO, so a leaf exception like
`DuplicateComponent` (a `ConflictError`) is caught by the `ConflictError`
handler without needing its own registration.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.exceptions import (
    AgentABIError,
    AuthenticationError,
    ConflictError,
    GitHubAuthorizationDenied,
    GitHubIdentityLookupFailed,
    GitHubOAuthNotConfigured,
    GitHubTokenExchangeFailed,
    GraphUnavailable,
    InvalidCompatibilityComparison,
    InvalidComponentContent,
    InvalidDependencyRelationship,
    InvalidReplaySubstitution,
    InvalidTrajectoryEvent,
    MalformedGitHubIdentity,
    MissingAuthorizationCode,
    NotFoundError,
    OAuthStateInvalid,
    OAuthStateStoreUnavailable,
    OrganizationAccessDenied,
    PermissionDenied,
    ProjectAccessDenied,
    ReplayExecutionFailed,
    ReplayExecutorUnavailable,
    SchemaNormalizationError,
    TrajectoryPayloadTooLarge,
    UnsupportedCompatibilityType,
)


def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return _error_response(404, str(exc))

    @app.exception_handler(ConflictError)
    async def handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
        return _error_response(409, str(exc))

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
        response = _error_response(401, str(exc))
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    @app.exception_handler(InvalidComponentContent)
    async def handle_invalid_content(
        request: Request, exc: InvalidComponentContent
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(InvalidDependencyRelationship)
    async def handle_invalid_dependency_relationship(
        request: Request, exc: InvalidDependencyRelationship
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(GraphUnavailable)
    async def handle_graph_unavailable(request: Request, exc: GraphUnavailable) -> JSONResponse:
        return _error_response(503, str(exc))

    @app.exception_handler(InvalidCompatibilityComparison)
    async def handle_invalid_compatibility_comparison(
        request: Request, exc: InvalidCompatibilityComparison
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(UnsupportedCompatibilityType)
    async def handle_unsupported_compatibility_type(
        request: Request, exc: UnsupportedCompatibilityType
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(SchemaNormalizationError)
    async def handle_schema_normalization_error(
        request: Request, exc: SchemaNormalizationError
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(InvalidTrajectoryEvent)
    async def handle_invalid_trajectory_event(
        request: Request, exc: InvalidTrajectoryEvent
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(TrajectoryPayloadTooLarge)
    async def handle_trajectory_payload_too_large(
        request: Request, exc: TrajectoryPayloadTooLarge
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(InvalidReplaySubstitution)
    async def handle_invalid_replay_substitution(
        request: Request, exc: InvalidReplaySubstitution
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(ReplayExecutorUnavailable)
    async def handle_replay_executor_unavailable(
        request: Request, exc: ReplayExecutorUnavailable
    ) -> JSONResponse:
        return _error_response(503, str(exc))

    @app.exception_handler(ReplayExecutionFailed)
    async def handle_replay_execution_failed(
        request: Request, exc: ReplayExecutionFailed
    ) -> JSONResponse:
        return _error_response(422, str(exc))

    @app.exception_handler(OAuthStateInvalid)
    async def handle_oauth_state_invalid(request: Request, exc: OAuthStateInvalid) -> JSONResponse:
        return _error_response(401, str(exc))

    @app.exception_handler(GitHubAuthorizationDenied)
    async def handle_github_authorization_denied(
        request: Request, exc: GitHubAuthorizationDenied
    ) -> JSONResponse:
        return _error_response(401, str(exc))

    @app.exception_handler(MissingAuthorizationCode)
    async def handle_missing_authorization_code(
        request: Request, exc: MissingAuthorizationCode
    ) -> JSONResponse:
        return _error_response(400, str(exc))

    @app.exception_handler(GitHubTokenExchangeFailed)
    async def handle_github_token_exchange_failed(
        request: Request, exc: GitHubTokenExchangeFailed
    ) -> JSONResponse:
        return _error_response(502, str(exc))

    @app.exception_handler(GitHubIdentityLookupFailed)
    async def handle_github_identity_lookup_failed(
        request: Request, exc: GitHubIdentityLookupFailed
    ) -> JSONResponse:
        return _error_response(502, str(exc))

    @app.exception_handler(MalformedGitHubIdentity)
    async def handle_malformed_github_identity(
        request: Request, exc: MalformedGitHubIdentity
    ) -> JSONResponse:
        return _error_response(502, str(exc))

    @app.exception_handler(OAuthStateStoreUnavailable)
    async def handle_oauth_state_store_unavailable(
        request: Request, exc: OAuthStateStoreUnavailable
    ) -> JSONResponse:
        return _error_response(503, str(exc))

    @app.exception_handler(GitHubOAuthNotConfigured)
    async def handle_github_oauth_not_configured(
        request: Request, exc: GitHubOAuthNotConfigured
    ) -> JSONResponse:
        return _error_response(503, str(exc))

    @app.exception_handler(PermissionDenied)
    async def handle_permission_denied(request: Request, exc: PermissionDenied) -> JSONResponse:
        return _error_response(403, str(exc))

    @app.exception_handler(OrganizationAccessDenied)
    async def handle_organization_access_denied(
        request: Request, exc: OrganizationAccessDenied
    ) -> JSONResponse:
        return _error_response(404, str(exc))

    @app.exception_handler(ProjectAccessDenied)
    async def handle_project_access_denied(
        request: Request, exc: ProjectAccessDenied
    ) -> JSONResponse:
        return _error_response(404, str(exc))

    @app.exception_handler(AgentABIError)
    async def handle_generic_domain_error(request: Request, exc: AgentABIError) -> JSONResponse:
        return _error_response(400, str(exc))
