"""ComponentRegistryService — integration tests against a real Postgres
(see the `session`/`db_engine` fixtures in conftest.py)."""

import uuid

import pytest

from app.domain.enums import ComponentStatus, ComponentType
from app.domain.exceptions import (
    ComponentNotFound,
    ComponentVersionNotFound,
    DuplicateComponent,
    DuplicateComponentVersion,
    InvalidComponentContent,
    ProjectNotFound,
)
from app.models import Organization, Project
from app.services.component_registry import ComponentRegistryService


async def _make_project(session, *, org_slug="acme", project_slug="payments") -> Project:
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    return project


def test_service_exposes_no_version_mutation_methods():
    # Immutability at the service/API boundary: there simply is no way to
    # ask the service to change an existing version's content.
    assert not hasattr(ComponentRegistryService, "update_component_version")
    assert not hasattr(ComponentRegistryService, "delete_component_version")


async def test_create_component_success(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)

    component = await service.create_component(
        project_id=project.id,
        component_type=ComponentType.PROMPT,
        name="Greeting Prompt",
        slug="greeting-prompt",
    )

    assert component.id is not None
    assert component.status == ComponentStatus.ACTIVE
    assert component.organization_id == project.organization_id


async def test_create_component_unknown_project_raises(session):
    service = ComponentRegistryService(session)
    with pytest.raises(ProjectNotFound):
        await service.create_component(
            project_id=uuid.uuid4(), component_type=ComponentType.PROMPT, name="x", slug="x"
        )


async def test_duplicate_component_rejected(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    with pytest.raises(DuplicateComponent):
        await service.create_component(
            project_id=project.id,
            component_type=ComponentType.PROMPT,
            name="Greeting 2",
            slug="greeting",
        )


async def test_same_slug_allowed_for_different_component_type(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    component = await service.create_component(
        project_id=project.id,
        component_type=ComponentType.WORKFLOW,
        name="Greeting Flow",
        slug="greeting",
    )
    assert component.slug == "greeting"


async def test_create_component_version_success(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )

    version = await service.create_component_version(
        project_id=project.id,
        component_id=component.id,
        version="1",
        content={"template": "Hello {{name}}", "variables": ["name"]},
    )

    assert version.version == "1"
    assert len(version.checksum) == 64
    assert version.sequence is not None


async def test_duplicate_version_rejected(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    await service.create_component_version(
        project_id=project.id, component_id=component.id, version="1", content={"template": "hi"}
    )
    with pytest.raises(DuplicateComponentVersion):
        await service.create_component_version(
            project_id=project.id,
            component_id=component.id,
            version="1",
            content={"template": "hi again"},
        )


async def test_invalid_payload_rejected(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    with pytest.raises(InvalidComponentContent):
        await service.create_component_version(
            project_id=project.id,
            component_id=component.id,
            version="1",
            content={"not_a_template_field": "x"},
        )


async def test_latest_version_and_ordering(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    await service.create_component_version(
        project_id=project.id, component_id=component.id, version="1", content={"template": "v1"}
    )
    await service.create_component_version(
        project_id=project.id, component_id=component.id, version="2", content={"template": "v2"}
    )
    v3 = await service.create_component_version(
        project_id=project.id, component_id=component.id, version="v18", content={"template": "v3"}
    )

    latest = await service.get_latest_component_version(project.id, component.id)
    assert latest.id == v3.id
    assert latest.version == "v18"


async def test_historical_version_retrieval(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    v1 = await service.create_component_version(
        project_id=project.id, component_id=component.id, version="1", content={"template": "v1"}
    )
    await service.create_component_version(
        project_id=project.id, component_id=component.id, version="2", content={"template": "v2"}
    )

    fetched = await service.get_component_version(project.id, component.id, "1")
    assert fetched.id == v1.id
    assert fetched.content["template"] == "v1"


async def test_missing_version_raises(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    with pytest.raises(ComponentVersionNotFound):
        await service.get_component_version(project.id, component.id, "nope")


async def test_checksum_determinism_across_versions_with_same_content(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component_a = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="A", slug="a"
    )
    component_b = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="B", slug="b"
    )
    v1 = await service.create_component_version(
        project_id=project.id,
        component_id=component_a.id,
        version="1",
        content={"template": "hi", "variables": []},
    )
    v2 = await service.create_component_version(
        project_id=project.id,
        component_id=component_b.id,
        version="1",
        content={"variables": [], "template": "hi"},  # same content, different key order
    )
    assert v1.checksum == v2.checksum


async def test_checksum_changes_with_content(session):
    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    v1 = await service.create_component_version(
        project_id=project.id, component_id=component.id, version="1", content={"template": "hi"}
    )
    v2 = await service.create_component_version(
        project_id=project.id, component_id=component.id, version="2", content={"template": "bye"}
    )
    assert v1.checksum != v2.checksum


async def test_project_isolation_components_not_visible_across_projects(session):
    project_a = await _make_project(session, org_slug="acme", project_slug="payments")
    project_b = await _make_project(session, org_slug="globex", project_slug="billing")
    service = ComponentRegistryService(session)

    component_a = await service.create_component(
        project_id=project_a.id, component_type=ComponentType.PROMPT, name="A", slug="shared-slug"
    )
    await service.create_component(
        project_id=project_b.id, component_type=ComponentType.PROMPT, name="B", slug="shared-slug"
    )

    with pytest.raises(ComponentNotFound):
        await service.get_component(project_b.id, component_a.id)

    page_b = await service.list_components(project_b.id)
    assert all(c.project_id == project_b.id for c in page_b.items)
    assert component_a.id not in {c.id for c in page_b.items}


async def test_version_content_is_immutable_at_db_level(session):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    project = await _make_project(session)
    service = ComponentRegistryService(session)
    component = await service.create_component(
        project_id=project.id, component_type=ComponentType.PROMPT, name="Greeting", slug="greeting"
    )
    version = await service.create_component_version(
        project_id=project.id, component_id=component.id, version="1", content={"template": "hi"}
    )
    await session.commit()

    with pytest.raises(DBAPIError):
        await session.execute(
            text("UPDATE component_versions SET content = CAST(:content AS jsonb) WHERE id = :id"),
            {"content": '{"template": "changed"}', "id": str(version.id)},
        )
    await session.rollback()
