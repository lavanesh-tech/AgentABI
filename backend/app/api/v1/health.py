"""Liveness/readiness endpoints.

`/health` proves only that the process is up and configuration loaded —
it never touches the database. `/ready` is the separate, honest readiness
probe: it actually queries Postgres and reports 503 if that fails, so it
can back a Kubernetes readinessProbe without lying about dependencies that
aren't reachable yet.
"""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.core.database import check_database_connection

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str


class ReadinessResponse(BaseModel):
    status: str
    database: bool


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    database_ok = await check_database_connection()
    if not database_ok:
        response.status_code = 503
    return ReadinessResponse(status="ok" if database_ok else "unavailable", database=database_ok)
