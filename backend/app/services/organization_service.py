"""OrganizationService — the first-organization onboarding use case
(task: "Implement the missing first-organization / first-OWNER
onboarding flow"). Mirrors `ProjectService`'s shape: a thin service
around one or two repositories, explicit transaction ownership, no
business logic in the route.

This service is deliberately narrow: it only ever creates a caller's
*first* organization, assigning that caller OWNER of it. It is not a
general "create organization"/"join organization"/"invite" API — those
remain out of scope (see docs/DECISIONS.md, ADR-040 follow-up).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.actions import AuditAction
from app.domain.exceptions import OrganizationAlreadyProvisioned
from app.domain.slugs import generate_unique_slug
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember, OrganizationRole
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.services.audit_service import AuditService


@dataclass(frozen=True)
class OnboardingResult:
    organization: Organization
    membership: OrganizationMember


class OrganizationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._organizations = OrganizationRepository(session)
        self._members = OrganizationMemberRepository(session)
        self._audit = AuditService(session)

    async def onboard_first_organization(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        request_id: str | None = None,
    ) -> OnboardingResult:
        """Create the caller's first `Organization` and grant them OWNER
        of it, atomically. Server-side rules enforced here (never trust
        the request body or the caller's token for any of this):

        1. The caller's identity (`user_id`) is passed in by the route
           from the authenticated principal only — never from the
           request body.
        2. `lock_user_for_onboarding` takes a row lock on the caller's
           own `User` row for the duration of this transaction, so two
           concurrent onboarding requests for the *same* user serialize
           instead of racing (see that method's docstring for why the
           `organization_members` unique constraint alone isn't enough).
        3. Membership is reloaded from the database inside that locked
           section — if the caller already has *any* membership, this
           raises `OrganizationAlreadyProvisioned` rather than adding a
           second organization or joining an existing one.
        4. The new `OrganizationMember` row is always `role=OWNER` for
           the newly created organization only — there is no code path
           here that can assign OWNER (or any role) on an existing
           organization, or assign any other user as owner.
        """

        locked_user = await self._organizations.lock_user_for_onboarding(user_id)
        if locked_user is None:
            # The caller was already authenticated by `get_current_user`
            # against this same `user_id`, so this should be unreachable
            # in practice; fail closed rather than proceed on a user row
            # that no longer exists.
            raise OrganizationAlreadyProvisioned(user_id)

        existing_memberships = await self._members.list_for_user(user_id)
        if existing_memberships:
            raise OrganizationAlreadyProvisioned(user_id)

        organization = Organization(name=name, slug=generate_unique_slug(name))
        self._organizations.add(organization)
        # Flush (not commit) to have Postgres assign the DB-generated
        # UUID primary key so the membership row below can reference it,
        # while keeping both inserts in the same transaction.
        await self._session.flush()

        membership = OrganizationMember(
            organization_id=organization.id,
            user_id=user_id,
            role=OrganizationRole.OWNER,
        )
        self._members.add(membership)

        self._audit.record(
            action=AuditAction.ORGANIZATION_CREATED,
            organization_id=organization.id,
            actor_user_id=user_id,
            resource_type="organization",
            resource_id=organization.id,
            request_id=request_id,
            metadata={"name": organization.name, "slug": organization.slug},
        )

        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise OrganizationAlreadyProvisioned(user_id) from exc

        await self._session.refresh(organization)
        await self._session.refresh(membership)
        return OnboardingResult(organization=organization, membership=membership)
