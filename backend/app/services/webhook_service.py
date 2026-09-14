"""GitHubWebhookService — the single place a verified webhook delivery
is turned into a persisted, idempotent, audited record (Security Phase
E spec §10). The route (`app/api/v1/github_webhook.py`) stays thin: it
reads the raw body and headers and calls this service; no SQL and no
signature logic in the route itself.

Scope (spec §11): this phase only trusts and records inbound events —
it does not trigger the compatibility pipeline or process PR/check
payloads. `event_type` is recorded as opaque metadata for a future
product phase to consume.
"""

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.core.config import Settings
from app.domain.exceptions import (
    GitHubWebhookNotConfigured,
    InvalidWebhookSignature,
    MissingWebhookDeliveryId,
    MissingWebhookSignature,
    WebhookDeliveryConflict,
)
from app.github.webhook_models import WebhookDeliveryStatus
from app.github.webhook_signature import compute_payload_hash, verify_signature
from app.models.github_webhook_delivery import GitHubWebhookDelivery
from app.repositories.webhook_delivery_repository import WebhookDeliveryRepository
from app.services.audit_service import AuditService


@dataclass(frozen=True)
class WebhookProcessResult:
    status: Literal["accepted", "duplicate"]
    delivery_id: str
    event_type: str


class GitHubWebhookService:
    def __init__(self, session: AsyncSession, *, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._deliveries = WebhookDeliveryRepository(session)
        self._audit = AuditService(session)

    async def process(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
        delivery_id: str | None,
        event_type: str | None,
        request_id: str | None,
    ) -> WebhookProcessResult:
        if not self._settings.github_webhook_secret:
            raise GitHubWebhookNotConfigured()

        if not signature_header:
            self._record_rejection(delivery_id, event_type, request_id, "missing_signature")
            await self._session.commit()
            raise MissingWebhookSignature()

        if not verify_signature(self._settings.github_webhook_secret, raw_body, signature_header):
            self._record_rejection(delivery_id, event_type, request_id, "invalid_signature")
            await self._session.commit()
            raise InvalidWebhookSignature()

        # Only past this point is anything about the request trusted —
        # headers and payload alike (spec §7).
        if not delivery_id:
            raise MissingWebhookDeliveryId()

        payload_hash = compute_payload_hash(raw_body)
        event_type = event_type or "unknown"

        existing = await self._deliveries.get_by_delivery_id(delivery_id)
        if existing is not None:
            if existing.payload_hash == payload_hash:
                # Identical redelivery (spec §9) — idempotent, no new
                # row, no duplicate audit/processing side effects.
                return WebhookProcessResult(
                    status="duplicate", delivery_id=delivery_id, event_type=event_type
                )
            self._record_rejection(delivery_id, event_type, request_id, "delivery_id_conflict")
            await self._session.commit()
            raise WebhookDeliveryConflict(delivery_id)

        # Parsed only to confirm the body is well-formed JSON — no field
        # of it is trusted or persisted (spec §8: metadata + hash only,
        # not the full payload).
        with contextlib.suppress(ValueError):
            json.loads(raw_body)

        now = datetime.now(UTC)
        delivery = GitHubWebhookDelivery(
            delivery_id=delivery_id,
            event_type=event_type,
            status=WebhookDeliveryStatus.PROCESSED,
            payload_hash=payload_hash,
            received_at=now,
            processed_at=now,
            request_id=request_id,
        )
        self._deliveries.add(delivery)
        self._audit.record(
            action=AuditAction.GITHUB_WEBHOOK_PROCESSED,
            resource_type="github_webhook_delivery",
            resource_id=delivery_id,
            request_id=request_id,
            metadata={"event_type": event_type},
        )

        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Race-condition safety net, same pattern as
            # TrajectoryRecorderService.start_trajectory: two concurrent
            # deliveries with the same id both passed the pre-check.
            await self._session.rollback()
            existing = await self._deliveries.get_by_delivery_id(delivery_id)
            if existing is not None:
                if existing.payload_hash == payload_hash:
                    return WebhookProcessResult(
                        status="duplicate", delivery_id=delivery_id, event_type=event_type
                    )
                raise WebhookDeliveryConflict(delivery_id) from exc
            raise
        await self._session.commit()
        return WebhookProcessResult(
            status="accepted", delivery_id=delivery_id, event_type=event_type
        )

    def _record_rejection(
        self,
        delivery_id: str | None,
        event_type: str | None,
        request_id: str | None,
        reason: str,
    ) -> None:
        # Safe to record even before signature success (spec §19):
        # `delivery_id`/`event_type` are treated as opaque header
        # strings here, never parsed/trusted as payload content, and
        # redacted the same as every other audit metadata dict.
        self._audit.record(
            action=AuditAction.GITHUB_WEBHOOK_REJECTED,
            resource_type="github_webhook_delivery",
            resource_id=delivery_id,
            request_id=request_id,
            metadata={"event_type": event_type, "reason": reason},
        )
