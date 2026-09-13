"""Aggregates all v1 API routers. Later phases add routers here (scans,
graph, replay, github webhook, ...) rather than growing main.py."""

from fastapi import APIRouter

from app.api.v1.compatibility import router as compatibility_router
from app.api.v1.components import router as components_router
from app.api.v1.graph import router as graph_router
from app.api.v1.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(components_router)
api_router.include_router(graph_router)
api_router.include_router(compatibility_router)
