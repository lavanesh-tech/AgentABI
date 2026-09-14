"""AuthorizationService — the single place "is this identity allowed to
do X" is decided (Security Phase C spec §6). Route dependencies
(`app/api/deps/authz.py`) call this; nothing else queries
`OrganizationMemberRepository` for a permission decision.

Every check reloads membership from PostgreSQL for the *target
resource's* organization — never trusts `AuthenticatedPrincipal.role`
(which reflects the JWT's `org_id`, possibly a different organization
than the one being accessed) and never trusts a JWT-carried
`organization_id` as authorization, only as routing context (spec §5/
§18, consistent with ADR-038). A membership fetched for organization A
is never reused to authorize a request against organization B, even
within the same call chain — each `authorize_*` call is independently
correct for its own `organization_id` argument.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import AuthenticatedPrincipal
from app.authz.context import AuthorizationDecision
from app.authz.permissions import Permission, role_has_permission
from app.core.logging import get_logger
from app.domain.exceptions import (
    OrganizationAccessDenied,
    PermissionDenied,
    ProjectAccessDenied,
    ProjectNotFound,
)
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository

logger = get_logger(__name__)


class AuthorizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._members = OrganizationMemberRepository(session)
        self._projects = ProjectRepository(session)

    async def authorize_organization_access(
        self,
        *,
        principal: AuthenticatedPrincipal,
        organization_id: uuid.UUID,
        permission: Permission,
    ) -> OrganizationMember:
        """Verify `principal` has a current membership in
        `organization_id` with `permission`. Always reloads the
        membership fresh — see module docstring. Raises
        `OrganizationAccessDenied` (404) if there is no membership at
        all, `PermissionDenied` (403) if there is a membership but its
        role lacks `permission`."""

        membership = await self._members.get_for_user_and_organization(
            principal.user_id, organization_id
        )
        if membership is None:
            self._log_decision(
                principal.user_id,
                organization_id,
                "organization",
                organization_id,
                permission,
                False,
            )
            raise OrganizationAccessDenied()

        if not role_has_permission(membership.role.value, permission):
            self._log_decision(
                principal.user_id,
                organization_id,
                "organization",
                organization_id,
                permission,
                False,
            )
            raise PermissionDenied()

        self._log_decision(
            principal.user_id, organization_id, "organization", organization_id, permission, True
        )
        return membership

    async def authorize_project_access(
        self,
        *,
        principal: AuthenticatedPrincipal,
        project_id: uuid.UUID,
        permission: Permission,
    ) -> tuple[Project, OrganizationMember]:
        """Resolve `project_id`, then verify `principal` has a current
        membership in *that project's* organization with `permission` —
        never a caller-supplied/JWT organization_id (spec §8/§18).

        `project_id` is the only identifier a nested-resource route has
        (every existing project-scoped router is mounted under
        `/projects/{project_id}/...`), so the project must be loaded to
        learn its `organization_id` before membership can be checked;
        this is not the "trust caller org context" anti-pattern spec §8
        warns against, since the organization used for the check always
        comes from the freshly-loaded `Project` row, never from the
        caller. Raises `ProjectNotFound` (404) if the project doesn't
        exist, `ProjectAccessDenied` (404, deliberately identical) if it
        exists but the caller has no membership in its organization, or
        `PermissionDenied` (403) if the caller is a member but lacks
        `permission`.
        """

        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)

        membership = await self._members.get_for_user_and_organization(
            principal.user_id, project.organization_id
        )
        if membership is None:
            self._log_decision(
                principal.user_id, project.organization_id, "project", project_id, permission, False
            )
            raise ProjectAccessDenied()

        if not role_has_permission(membership.role.value, permission):
            self._log_decision(
                principal.user_id, project.organization_id, "project", project_id, permission, False
            )
            raise PermissionDenied()

        self._log_decision(
            principal.user_id, project.organization_id, "project", project_id, permission, True
        )
        return project, membership

    @staticmethod
    def _log_decision(
        actor_user_id: uuid.UUID,
        organization_id: uuid.UUID,
        resource_type: str,
        resource_id: uuid.UUID | None,
        permission: Permission,
        allowed: bool,
    ) -> AuthorizationDecision:
        decision = AuthorizationDecision(
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            permission=permission,
            allowed=allowed,
        )
        # Structured, not persisted (spec §20 — persistence is Security
        # Phase E). Every field a future audit-event row needs is
        # already here as a typed object, not a log-string to re-parse.
        logger.info(
            "authorization_decision",
            actor_user_id=str(decision.actor_user_id),
            organization_id=str(decision.organization_id),
            resource_type=decision.resource_type,
            resource_id=str(decision.resource_id) if decision.resource_id else None,
            permission=decision.permission.value,
            allowed=decision.allowed,
        )
        return decision
