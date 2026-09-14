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
    AUDIT_READ = "audit:read"
    DIFFERENTIAL_READ = "differential:read"
    DIFFERENTIAL_EXECUTE = "differential:execute"
    RISK_READ = "risk:read"
    RISK_EXECUTE = "risk:execute"
    GITHUB_INTEGRATION_READ = "github_integration:read"
    GITHUB_INTEGRATION_MANAGE = "github_integration:manage"


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
        # Phase 10 spec §22: MEMBER may read differential reports, same
        # bucket as every other read-only resource — reading derived
        # evidence isn't a privileged action, only computing it is.
        Permission.DIFFERENTIAL_READ,
        # Phase 11 spec §25: MEMBER may read risk assessments, same
        # read-only bucket as every other derived-evidence resource.
        Permission.RISK_READ,
        # Phase 12 spec §34: MEMBER may read GitHub repository mappings.
        Permission.GITHUB_INTEGRATION_READ,
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
        # Phase 10 spec §22: running a differential analysis is a
        # privileged engineering action (same bucket as SCAN_EXECUTE/
        # REPLAY_EXECUTE) — MEMBER never triggers analysis, only reads
        # results.
        Permission.DIFFERENTIAL_EXECUTE,
        # Phase 11 spec §25: running a risk assessment is a privileged
        # engineering action, same bucket as DIFFERENTIAL_EXECUTE —
        # MEMBER never triggers one, only reads results.
        Permission.RISK_EXECUTE,
        # Phase 12 spec §34: creating/deleting a GitHub repository
        # mapping is a privileged engineering action, same bucket as
        # RISK_EXECUTE/DIFFERENTIAL_EXECUTE.
        Permission.GITHUB_INTEGRATION_MANAGE,
        # Security Phase E spec §17: ADMIN may read the organization's
        # audit trail (a privileged engineering/security action, same
        # bucket as SCAN_EXECUTE/REPLAY_EXECUTE) — only membership
        # management/org management stay OWNER-only.
        Permission.AUDIT_READ,
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
