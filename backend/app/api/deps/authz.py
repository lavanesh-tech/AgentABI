"""Authorization dependencies (Security Phase C spec §6) — the only
place a route declares "this action needs permission X". Every
project-scoped router (`components.py`, `compatibility.py`,
`trajectories.py`, `replays.py`, `graph.py`) is mounted under
`/projects/{project_id}/...`, so one dependency factory,
`require_project_permission(permission)`, covers all of them: it reads
`project_id` from the path (FastAPI injects it by parameter name, same
as every route handler already does), authenticates via Phase A's
`get_current_user`, and authorizes via `AuthorizationService`.

Nested resources (a component version, a scan, a trajectory event, a
replay step) never get their own authorization dependency — they are
only ever reached through a `project_id`-scoped route, and every
repository in this codebase already scopes its resource lookups by
`project_id` (see e.g. `ComponentRepository.get_by_id`), so a resource
ID from another project can never resolve even after this dependency
passes. Authorization happens once, before the route body runs.
"""

import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import get_current_user
from app.auth.principal import AuthenticatedPrincipal
from app.authz.permissions import Permission
from app.authz.service import AuthorizationService
from app.core.database import get_db_session
from app.models.organization_member import OrganizationMember
from app.models.project import Project


def require_project_permission(permission: Permission):
    """Returns a FastAPI dependency that authorizes `permission` against
    the `project_id` path parameter of whatever route depends on it,
    and returns the resolved `(Project, OrganizationMember)` so the
    route/service can reuse it instead of re-fetching (spec §29 —
    request-scoped reuse where practical; the service layer's own
    `_require_project`-style lookups still run a second fetch today,
    documented in ARCHITECTURE.md as an accepted tradeoff)."""

    async def _dependency(
        project_id: uuid.UUID,
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> tuple[Project, OrganizationMember]:
        return await AuthorizationService(session).authorize_project_access(
            principal=principal, project_id=project_id, permission=permission
        )

    return _dependency


def require_organization_permission(permission: Permission):
    """Returns a FastAPI dependency that authorizes `permission` against
    the `organization_id` path parameter of whatever route depends on
    it. Not yet used by any shipped route (Phase C ships no organization/
    membership-management endpoints — spec §16), but available for
    Security Phase E+ to depend on without re-deriving this pattern."""

    async def _dependency(
        organization_id: uuid.UUID,
        principal: Annotated[AuthenticatedPrincipal, Depends(get_current_user)],
        session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> OrganizationMember:
        return await AuthorizationService(session).authorize_organization_access(
            principal=principal, organization_id=organization_id, permission=permission
        )

    return _dependency
