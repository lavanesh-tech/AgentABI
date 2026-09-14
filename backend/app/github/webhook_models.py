"""Pure types for GitHub webhook delivery status (Security Phase E).
Stdlib enum only — no SQLAlchemy import, mirrors
`app/authz/permissions.py`'s dependency-free design."""

import enum


class WebhookDeliveryStatus(enum.StrEnum):
    PROCESSED = "processed"
    REJECTED = "rejected"
