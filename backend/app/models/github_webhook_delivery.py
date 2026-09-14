"""GitHubWebhookDelivery — durable record of one signature-verified
GitHub webhook delivery (Security Phase E spec §8). Persisted so
duplicate-delivery detection works across API instances and restarts —
never a process-local dict, which a retried delivery hitting a different
instance (or the same instance after a restart) would silently miss.

`payload_hash` (SHA-256 of the exact raw body bytes,
`app/github/webhook_signature.compute_payload_hash`) is stored instead
of the full payload by default (spec §8: "avoid persisting full webhook
payload unless needed") — enough to detect an identical-hash retry
(idempotent) vs. a same-id-different-content anomaly (conflict, spec
§9), without growing this table with arbitrary GitHub payload JSON.
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.github.webhook_models import WebhookDeliveryStatus
from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _status_values(enum_cls: type[WebhookDeliveryStatus]) -> list[str]:
    return [member.value for member in enum_cls]


class GitHubWebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "github_webhook_deliveries"

    # GitHub's own delivery identifier (`X-GitHub-Delivery`) — unique per
    # delivery attempt series; a retried delivery reuses the same value
    # (migration 0007's unique constraint is the idempotency backstop).
    delivery_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[WebhookDeliveryStatus] = mapped_column(
        Enum(
            WebhookDeliveryStatus,
            name="github_webhook_delivery_status",
            values_callable=_status_values,
        ),
        nullable=False,
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"GitHubWebhookDelivery(delivery_id={self.delivery_id!r}, status={self.status!r})"
