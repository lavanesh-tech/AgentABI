"""Aggregates all v1 API routers. Later phases add routers here (components,
scans, graph, replay, github webhook, ...) rather than growing main.py."""

from fastapi import APIRouter

from app.api.v1.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
