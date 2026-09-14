"""Structured authorization decisions (Security Phase C spec §20 —
"audit preparation"). `AuthorizationDecision` is the shape a future
Security Phase E audit-log table would persist; this phase only
constructs it (and logs it — see `app/authz/service.py`), never persists
it. Pure stdlib dataclass, no SQLAlchemy/FastAPI import.
"""

import uuid
from dataclasses import dataclass

from app.authz.permissions import Permission


@dataclass(frozen=True)
class AuthorizationDecision:
    """Everything a future audit-event row would need: who, on behalf of
    which organization, tried to do what to which resource, and whether
    it was allowed. `resource_id` is `None` for organization-level
    decisions that aren't about one specific resource (e.g. "can this
    user manage membership in this org at all")."""

    actor_user_id: uuid.UUID
    organization_id: uuid.UUID
    resource_type: str
    resource_id: uuid.UUID | None
    permission: Permission
    allowed: bool
