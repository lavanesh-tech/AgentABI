"""Membership-mutation authorization (Security Phase C spec §16/§17).
No membership-mutation API route exists yet (spec §16: "if membership
mutation APIs do not yet exist, test permission logic at service/domain
level and document the future route" — see ARCHITECTURE.md for the
documented future `PATCH /organizations/{organization_id}/members/
{user_id}` route). This module is the authorization decision such a
route would call, kept here and tested now so the route itself is a
thin wrapper when it ships.

`authorize_role_change` is pure (no DB) so it's `pytest --noconftest`-
executable — it takes plain string roles/bools, never an ORM object or
a session, mirroring `app/authz/permissions.py`.
"""

from app.authz.permissions import Permission, role_has_permission
from app.domain.exceptions import PermissionDenied


def authorize_role_change(
    *,
    actor_role: str | None,
    target_current_role: str,
    new_role: str,
    is_last_owner: bool,
) -> None:
    """Raises `PermissionDenied` for any unsafe or unauthorized role
    change; returns `None` (silently) if the change is allowed.

    Only `MEMBERSHIP_MANAGE` (OWNER-only in this codebase's
    `ROLE_PERMISSIONS` — see ADR-041) may change any membership at all.
    This alone closes three of spec §17's cases: a MEMBER can never
    promote itself (MEMBER has no `MEMBERSHIP_MANAGE`), an ADMIN can
    never promote itself to OWNER or touch anyone else's role (ADMIN
    has no `MEMBERSHIP_MANAGE` either — see ADR-041 for why ADMIN gets
    none rather than a partial grant), and the "assign roles in another
    organization" case is closed one layer up, by
    `AuthorizationService.authorize_organization_access` always
    resolving `actor_role` fresh for the *target* organization, never
    reusing a role checked against a different one.

    The remaining case this function alone is responsible for: an OWNER
    must not be able to demote/remove the organization's last OWNER
    (itself or another OWNER) — that would leave the organization with
    no one able to manage membership at all, an unrecoverable state
    without direct database access. Demoting/removing a non-last OWNER,
    or changing any non-OWNER membership, is allowed.
    """

    if not role_has_permission(actor_role, Permission.MEMBERSHIP_MANAGE):
        raise PermissionDenied()

    if target_current_role == "owner" and new_role != "owner" and is_last_owner:
        raise PermissionDenied("Cannot remove the organization's last owner")
