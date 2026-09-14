"""Centralized permission model (Security Phase C spec §4). The only
place a role is mapped to what it can do — nothing in a route or service
should ever compare `role == OrganizationRole.ADMIN` directly; it should
depend on `require_project_permission(Permission.X)`
(`app/api/deps/authz.py`), which consults `ROLE_PERMISSIONS` here.

Deliberately keyed by the role's plain string value ("owner"/"admin"/
"member"), not by `app.models.organization_member.OrganizationRole`
itself: importing that enum pulls in SQLAlchemy via `app.models`'s
package `__init__.py` (the same tradeoff `app/auth/principal.py`
documents), and this module is worth keeping genuinely dependency-free —
pure stdlib `enum` only, so it's `pytest --noconftest`-executable, same
testability choice as `app/compatibility/`, `app/trajectory/`,
`app/replay/`, `app/auth/jwt.py`. Call sites (`app/authz/service.py`)
pass `membership.role.value`.
"""

import enum


class Permission(enum.StrEnum):
    """One entry per distinct authorization decision this codebase
    currently makes. Deliberately resource-action pairs, not a full
    policy-engine DSL (spec §30 rules out OPA/Cedar/an external policy
    engine) — a `frozenset[Permission]` per role is the whole engine."""

    PROJECT_READ = "project:read"
    PROJECT_CREATE = "project:create"
    PROJECT_UPDATE = "project:update"
    COMPONENT_READ = "component:read"
    COMPONENT_WRITE = "component:write"
    SCAN_READ = "scan:read"
    SCAN_EXECUTE = "scan:execute"
    TRAJECTORY_READ = "trajectory:read"
    TRAJECTORY_WRITE = "trajectory:write"
    REPLAY_READ = "replay:read"
    REPLAY_EXECUTE = "replay:execute"
    GRAPH_READ = "graph:read"
    GRAPH_WRITE = "graph:write"
    MEMBERSHIP_MANAGE = "membership:manage"
    ORG_MANAGE = "org:manage"


# MEMBER: least-privilege, read-only across every organization-scoped
# resource (spec §3's "MEMBER" policy).
_MEMBER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.PROJECT_READ,
        Permission.COMPONENT_READ,
        Permission.SCAN_READ,
        Permission.TRAJECTORY_READ,
        Permission.REPLAY_READ,
        Permission.GRAPH_READ,
    }
)

# ADMIN: every MEMBER permission, plus every "privileged engineering
# action" the spec names (create/update projects, register components,
# run scans, execute replays, mutate the dependency graph) — but not
# membership/org management, which stays OWNER-only (spec §16/§17).
_ADMIN_PERMISSIONS: frozenset[Permission] = _MEMBER_PERMISSIONS | frozenset(
    {
        Permission.PROJECT_CREATE,
        Permission.PROJECT_UPDATE,
        Permission.COMPONENT_WRITE,
        Permission.SCAN_EXECUTE,
        Permission.TRAJECTORY_WRITE,
        Permission.REPLAY_EXECUTE,
        Permission.GRAPH_WRITE,
    }
)

# OWNER: every ADMIN permission, plus organization/membership management
# — the two actions explicitly reserved to OWNER (spec §3/§16/§17: an
# ADMIN must never be able to promote itself, or anyone, to OWNER, or
# otherwise manage membership).
_OWNER_PERMISSIONS: frozenset[Permission] = _ADMIN_PERMISSIONS | frozenset(
    {
        Permission.MEMBERSHIP_MANAGE,
        Permission.ORG_MANAGE,
    }
)

# Keyed by OrganizationRole.value ("owner"/"admin"/"member"), not the
# enum itself — see module docstring.
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "member": _MEMBER_PERMISSIONS,
    "admin": _ADMIN_PERMISSIONS,
    "owner": _OWNER_PERMISSIONS,
}


def role_has_permission(role: str | None, permission: Permission) -> bool:
    """`role=None` (no membership resolved for the target organization —
    see ADR-038/041) always denies, never falls back to a default-allow
    or a "no role means admin" special case. An unrecognized role string
    also denies (fails closed) rather than raising `KeyError`."""

    if role is None:
        return False
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
