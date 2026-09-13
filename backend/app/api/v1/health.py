"""Liveness/readiness endpoints.

`/health` proves only that the process is up and configuration loaded —
it never touches any external dependency. `/ready` is the separate,
honest readiness probe: it actually runs every check registered in
`app/core/readiness.py` (Postgres, Neo4j, and whatever future phases add)
and reports 503 if any of them fails, so it can back a Kubernetes
readinessProbe without lying about dependencies that aren't reachable
yet.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.readiness import run_readiness_checks

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    checks = await run_readiness_checks()
    all_ok = all(checks.values())
    if not all_ok:
        response.status_code = 503
    return ReadinessResponse(status="ok" if all_ok else "unavailable", checks=checks)
