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
    ConflictError,
    GraphUnavailable,
    InvalidComponentContent,
    InvalidDependencyRelationship,
    NotFoundError,
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

    @app.exception_handler(AgentABIError)
    async def handle_generic_domain_error(request: Request, exc: AgentABIError) -> JSONResponse:
        return _error_response(400, str(exc))
