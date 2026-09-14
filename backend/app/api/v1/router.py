"""Aggregates all v1 API routers. Later phases add routers here (scans,
graph, replay, github webhook, ...) rather than growing main.py."""

from fastapi import APIRouter

from app.api.v1.audit_events import router as audit_events_router
from app.api.v1.auth import router as auth_router
from app.api.v1.compatibility import router as compatibility_router
from app.api.v1.components import router as components_router
from app.api.v1.differential import router as differential_router
from app.api.v1.errors import COMMON_ERROR_RESPONSES
from app.api.v1.github_pr_analyses import router as github_pr_analyses_router
from app.api.v1.github_repositories import router as github_repositories_router
from app.api.v1.github_webhook import router as github_webhook_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router
from app.api.v1.projects import router as projects_router
from app.api.v1.replays import router as replays_router
from app.api.v1.risk import router as risk_router
from app.api.v1.trajectories import router as trajectories_router

api_router = APIRouter()
# `responses=COMMON_ERROR_RESPONSES` documents the standardized error
# envelope (Security Phase D) for common failure statuses on every route
# in a router, without repeating a `responses={...}` dict per route
# (Security Phase F spec §6). `health` is excluded — it has no auth/
# authz/validation surface to document failures for.
api_router.include_router(health_router)
api_router.include_router(auth_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(projects_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(components_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(graph_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(compatibility_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(trajectories_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(replays_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(differential_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(risk_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(github_repositories_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(github_pr_analyses_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(github_webhook_router, responses=COMMON_ERROR_RESPONSES)
api_router.include_router(audit_events_router, responses=COMMON_ERROR_RESPONSES)
