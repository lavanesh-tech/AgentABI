"""GitHub webhook ingestion API (Security Phase E spec §4). Deliberately
unauthenticated by AgentABI JWT — GitHub proves itself via the HMAC
request signature instead (spec §4) — but still rate limited (by client
identity, since no AgentABI user exists for this request) and covered
by Phase D's global request-size middleware. Route stays thin: raw body
+ headers in, `GitHubWebhookService` out; no signature logic or SQL
here.

Phase 12 adds one additive step (spec §2/§3): once a `pull_request`
delivery is newly accepted (never for a duplicate — idempotency stays
exactly Security Phase E's), the route best-effort dispatches
`GitHubPullRequestAnalysisService`. This is deliberately NOT inside
`GitHubWebhookService.process()` — that service's own tests (Security
Phase E) stay exactly as they were, and a PR-analysis/GitHub-publish
failure must never turn a successfully-recorded webhook delivery into a
non-202 response (spec §28): GitHub only needs to know the delivery was
received; the check result is a separate, independently-retryable
artifact visible on the PR itself.

Phase 13 (spec §13) adds the `KAFKA_ENABLED` branch inside that same
dispatch step: `false` keeps running the full deterministic pipeline
inline on this request (exactly Phase 12's behavior — the default, and
every local/unit-test default); `true` only persists the PENDING
analysis row and publishes an `github.pr.analysis.requested` event,
returning immediately — `app.kafka.worker` performs the actual pipeline
off this request thread.
"""

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.rate_limit import rate_limit_by_client
from app.audit.actions import AuditAction
from app.core.config import Settings, get_settings
from app.core.database import get_db_session
from app.domain.exceptions import AgentABIError
from app.events.analysis_events import build_analysis_requested_event
from app.events.factory import get_event_publisher
from app.github.checks_client import HttpxGitHubChecksClient, StaticGitHubCredentialProvider
from app.github.pr_webhook_models import parse_pull_request_event
from app.observability import record_github_webhook_delivery
from app.services.audit_service import AuditService
from app.services.github_pr_analysis_service import GitHubPullRequestAnalysisService
from app.services.webhook_service import GitHubWebhookService

logger = structlog.get_logger(__name__)

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

    event_header = request.headers.get("X-GitHub-Event") or "unknown"
    service = GitHubWebhookService(session, settings=settings)
    try:
        result = await service.process(
            raw_body=raw_body,
            signature_header=request.headers.get("X-Hub-Signature-256"),
            delivery_id=request.headers.get("X-GitHub-Delivery"),
            event_type=request.headers.get("X-GitHub-Event"),
            request_id=request_id,
        )
    except AgentABIError:
        # Spec §16: a rejected delivery (bad signature, missing headers,
        # webhook not configured) is a bounded "rejected" outcome — the
        # exception itself, delivery id, and headers are never used as
        # label values.
        record_github_webhook_delivery(settings, event=event_header, outcome="rejected")
        raise
    record_github_webhook_delivery(settings, event=result.event_type, outcome=result.status)

    if result.status == "accepted" and result.event_type == "pull_request":
        await _dispatch_pr_analysis(
            raw_body,
            session=session,
            settings=settings,
            delivery_id=result.delivery_id,
            request_id=request_id,
        )

    return WebhookAcceptedResponse(
        status=result.status, delivery_id=result.delivery_id, event_type=result.event_type
    )


async def _dispatch_pr_analysis(
    raw_body: bytes,
    *,
    session: AsyncSession,
    settings: Settings,
    delivery_id: str,
    request_id: str | None,
) -> None:
    """Best-effort (spec §2/§28): any failure here is logged, never
    raised — the webhook response above has already been decided."""

    try:
        payload = parse_pull_request_event(raw_body)
        if payload is None:
            return  # unsupported action (spec §4) — safely ignored

        checks_client = HttpxGitHubChecksClient(
            StaticGitHubCredentialProvider(settings.github_checks_token)
        )
        pr_service = GitHubPullRequestAnalysisService(session, checks_client=checks_client)

        if settings.kafka_enabled:
            analysis = await pr_service.start_analysis(
                payload, delivery_id=delivery_id, request_id=request_id
            )
            mapping = await pr_service.get_repository_mapping(analysis.github_repository_id)
            event = build_analysis_requested_event(
                github_pr_analysis_id=str(analysis.id),
                project_id=str(analysis.project_id),
                organization_id=str(analysis.organization_id),
                github_repository_id=analysis.github_repository_id,
                pull_request_number=analysis.pull_request_number,
                head_sha=analysis.head_sha,
                base_sha=analysis.base_sha,
                component_id=(
                    str(mapping.component_id) if mapping and mapping.component_id else None
                ),
                baseline_version=mapping.baseline_version if mapping else None,
                correlation_id=request_id or delivery_id,
            )
            await get_event_publisher(settings).publish(event)
            AuditService(session).record(
                action=AuditAction.KAFKA_ANALYSIS_ENQUEUED,
                organization_id=analysis.organization_id,
                resource_type="github_pr_analysis",
                resource_id=analysis.id,
                request_id=request_id,
                metadata={
                    "project_id": str(analysis.project_id),
                    "head_sha": analysis.head_sha,
                    "topic": settings.kafka_analysis_request_topic,
                },
            )
            await session.commit()
        else:
            await pr_service.analyze_pull_request(
                payload, delivery_id=delivery_id, request_id=request_id
            )
    except AgentABIError as exc:
        logger.warning(
            "github_pr_analysis_failed",
            delivery_id=delivery_id,
            error_type=type(exc).__name__,
        )
    except Exception:  # noqa: BLE001 - last line of defense, never crash the webhook route
        logger.exception("github_pr_analysis_unexpected_error", delivery_id=delivery_id)
