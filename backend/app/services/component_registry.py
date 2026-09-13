"""ComponentRegistryService — the single place business rules for
registering and versioning components live. API routes call this service;
they never touch repositories or ORM models directly.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.checksums import compute_checksum
from app.domain.component_content import validate_content
from app.domain.enums import ComponentStatus, ComponentType
from app.domain.exceptions import (
    ComponentNotFound,
    ComponentVersionNotFound,
    DuplicateComponent,
    DuplicateComponentVersion,
    ProjectNotFound,
)
from app.models.component import Component
from app.models.component_version import ComponentVersion
from app.models.project import Project
from app.repositories.component_repository import ComponentRepository
from app.repositories.component_version_repository import ComponentVersionRepository
from app.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    total: int
    page: int
    page_size: int


class ComponentRegistryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._components = ComponentRepository(session)
        self._versions = ComponentVersionRepository(session)
        self._projects = ProjectRepository(session)

    async def _require_project(self, project_id: uuid.UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise ProjectNotFound(project_id)
        return project

    async def create_component(
        self,
        *,
        project_id: uuid.UUID,
        component_type: ComponentType,
        name: str,
        slug: str,
        description: str | None = None,
    ) -> Component:
        project = await self._require_project(project_id)

        existing = await self._components.get_by_slug(project_id, component_type, slug)
        if existing is not None:
            raise DuplicateComponent(project_id, component_type, slug)

        component = Component(
            organization_id=project.organization_id,
            project_id=project_id,
            component_type=component_type,
            name=name,
            slug=slug,
            description=description,
            status=ComponentStatus.ACTIVE,
        )
        self._components.add(component)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Race-condition safety net: two concurrent requests both pass
            # the pre-check above, then both try to insert. The unique
            # constraint (project_id, component_type, slug) is what
            # actually prevents the duplicate; this just translates the
            # resulting IntegrityError into the same domain exception the
            # pre-check would have raised, instead of leaking a raw
            # database error to the caller.
            await self._session.rollback()
            raise DuplicateComponent(project_id, component_type, slug) from exc
        return component

    async def get_component(self, project_id: uuid.UUID, component_id: uuid.UUID) -> Component:
        await self._require_project(project_id)
        component = await self._components.get_by_id(project_id, component_id)
        if component is None:
            raise ComponentNotFound(component_id)
        return component

    async def list_components(
        self,
        project_id: uuid.UUID,
        *,
        component_type: ComponentType | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[Component]:
        await self._require_project(project_id)
        offset = (page - 1) * page_size
        items, total = await self._components.list_by_project(
            project_id, component_type, offset, page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    async def create_component_version(
        self,
        *,
        project_id: uuid.UUID,
        component_id: uuid.UUID,
        version: str,
        content: dict[str, object],
        version_metadata: dict[str, object] | None = None,
    ) -> ComponentVersion:
        component = await self.get_component(project_id, component_id)

        existing = await self._versions.get_by_version(component_id, version)
        if existing is not None:
            raise DuplicateComponentVersion(component_id, version)

        validated_content = validate_content(component.component_type, content)
        checksum = compute_checksum(validated_content)

        component_version = ComponentVersion(
            component_id=component_id,
            version=version,
            content=validated_content,
            checksum=checksum,
            version_metadata=version_metadata,
        )
        self._versions.add(component_version)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateComponentVersion(component_id, version) from exc
        return component_version

    async def get_component_version(
        self, project_id: uuid.UUID, component_id: uuid.UUID, version: str
    ) -> ComponentVersion:
        await self.get_component(project_id, component_id)
        component_version = await self._versions.get_by_version(component_id, version)
        if component_version is None:
            raise ComponentVersionNotFound(component_id, version)
        return component_version

    async def get_latest_component_version(
        self, project_id: uuid.UUID, component_id: uuid.UUID
    ) -> ComponentVersion:
        await self.get_component(project_id, component_id)
        component_version = await self._versions.get_latest(component_id)
        if component_version is None:
            raise ComponentVersionNotFound(component_id, "latest")
        return component_version

    async def list_component_versions(
        self,
        project_id: uuid.UUID,
        component_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[ComponentVersion]:
        await self.get_component(project_id, component_id)
        offset = (page - 1) * page_size
        items, total = await self._versions.list_by_component(component_id, offset, page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    # Deliberately no `update_component_version` (or `delete_component_version`)
    # method: immutability is enforced by this service simply never
    # offering a way to mutate a version's content. See
    # ComponentVersion's docstring for the database-level backstop.
