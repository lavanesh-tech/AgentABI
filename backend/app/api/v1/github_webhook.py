"""GitHub webhook ingestion API (Security Phase E spec §4). Deliberately
unauthenticated by AgentABI JWT — GitHub proves itself via the HMAC
request signature instead (spec §4) — but still rate limited (by client
identity, since no AgentABI user exists for this request) and covered
by Phase D's global request-size middleware. Route stays thin: raw body
+ headers in, `GitHubWebhookService` out; no signature logic or SQL
here.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.rate_limit import rate_limit_by_client
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.services.webhook_service import GitHubWebhookService

router = APIRouter(prefix="/github", tags=["github-webhook"])

_settings = get_settings()
# Reuses Phase D's mutation rate-limit knobs rather than adding a
# dedicated setting (spec §3: don't duplicate configuration). Keyed by
# client identity (app/api/deps/rate_limit.py's trusted-proxy-aware IP
# derivation) since no AgentABI user resolves this request.
_RATE_WEBHOOK = Depends(
    rate_limit_by_client(
        "github_webhook",
        _settings.rate_limit_mutation_requests,
        _settings.rate_limit_mutation_window_seconds,
    )
)


class WebhookAcceptedResponse(BaseModel):
    status: str
    delivery_id: str
    event_type: str


@router.post(
    "/webhook",
    response_model=WebhookAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_RATE_WEBHOOK],
    summary="Receive a GitHub webhook delivery",
    description="Public — no AgentABI JWT. GitHub authenticates via "
    "X-Hub-Signature-256 (HMAC-SHA256 over the raw body) instead. Requires "
    "X-Hub-Signature-256, X-GitHub-Delivery, and X-GitHub-Event headers.",
)
async def github_webhook(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> WebhookAcceptedResponse:
    # request.body() reads through the exact same ASGI receive callable
    # Phase D's RequestSizeLimitMiddleware wraps (it only counts bytes,
    # never rewrites them — see app/core/request_size.py) — these are
    # GitHub's original bytes, required for signature verification
    # (spec §5), never a re-serialized JSON representation.
    raw_body = await request.body()
    request_id = getattr(request.state, "correlation_id", None)

    service = GitHubWebhookService(session, settings=settings)
    result = await service.process(
        raw_body=raw_body,
        signature_header=request.headers.get("X-Hub-Signature-256"),
        delivery_id=request.headers.get("X-GitHub-Delivery"),
        event_type=request.headers.get("X-GitHub-Event"),
        request_id=request_id,
    )
    return WebhookAcceptedResponse(
        status=result.status, delivery_id=result.delivery_id, event_type=result.event_type
    )
