"""AuthenticatedPrincipal — the typed context routes actually work with,
never a raw decoded JWT dict and never an ORM `User`/`OrganizationMember`
passed around the application (Phase A spec §7).

Reuses the existing `OrganizationRole` enum from Phase 2's
`app/models/organization_member.py` rather than inventing a second role
type — the tradeoff is that, unlike `app/auth/jwt.py`/`claims.py`, this
module pulls in the ORM import chain (`app.models` -> SQLAlchemy) simply
by importing that enum, so it isn't independently `pytest --noconftest`-
runnable in this sandbox (same constraint as every module that touches
`app.models`).
"""

import uuid
from dataclasses import dataclass

from app.models.organization_member import OrganizationRole


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: uuid.UUID
    email: str
    organization_id: uuid.UUID | None
    role: OrganizationRole | None
