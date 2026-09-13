"""Liveness/readiness endpoints.

Phase 1 exposes a minimal health check that proves the process is up and
configuration loaded successfully. It deliberately does NOT probe Postgres/
Redis/Neo4j/Kafka yet — those dependency checks belong to their respective
phases once the clients exist, to avoid faking readiness.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str


@router.get("/health", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
    )
