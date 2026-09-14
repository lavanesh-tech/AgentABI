"""Aggregates all v1 API routers. Later phases add routers here (scans,
graph, replay, github webhook, ...) rather than growing main.py."""

from fastapi import APIRouter

from app.api.v1.audit_events import router as audit_events_router
from app.api.v1.auth import router as auth_router
from app.api.v1.compatibility import router as compatibility_router
from app.api.v1.components import router as components_router
from app.api.v1.github_webhook import router as github_webhook_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router
from app.api.v1.replays import router as replays_router
from app.api.v1.trajectories import router as trajectories_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(projects_router)
api_router.include_router(components_router)
api_router.include_router(graph_router)
api_router.include_router(compatibility_router)
api_router.include_router(trajectories_router)
api_router.include_router(replays_router)
api_router.include_router(github_webhook_router)
api_router.include_router(audit_events_router)
