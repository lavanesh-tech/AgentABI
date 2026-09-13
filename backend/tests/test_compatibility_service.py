"""CompatibilityService — integration tests against a real Postgres (see
the `session`/`db_engine` fixtures in conftest.py). These exercise scan
persistence, FK behavior, tenant isolation, immutability, and the
Postgres <-> `Change` mapping (JSONB old/new values, enum/status storage)
that `test_analyzer.py`'s pure tests can't cover.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.compatibility.models import Classification, CompatibilityStatus
from app.domain.enums import ComponentType
from app.domain.exceptions import (
    CompatibilityScanNotFound,
    ComponentNotFound,
    ComponentVersionNotFound,
    InvalidCompatibilityComparison,
)
from app.models import Organization, Project
from app.services.compatibility_service import CompatibilityService
from app.services.component_registry import ComponentRegistryService


async def _make_project(session, *, org_slug="acme", project_slug="payments") -> Project:
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    return project


async def _make_tool_component(registry, project, *, slug="authorize-payment"):
    component = await registry.create_component(
        project_id=project.id, component_type=ComponentType.TOOL, name=slug.title(), slug=slug
    )
    v1 = await registry.create_component_version(
        project_id=project.id,
        component_id=component.id,
        version="1",
        content={
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "amount": {"type": "number"},
                    "currency": {"type": "string"},
                },
                "required": ["customer_id", "amount", "currency"],
            },
            "output_schema": {"type": "object", "properties": {}},
        },
    )
    v2 = await registry.create_component_version(
        project_id=project.id,
        component_id=component.id,
        version="2",
        content={
            "input_schema": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "amount": {"type": "number"},
                },
                "required": ["user_id", "amount"],
            },
            "output_schema": {"type": "object", "properties": {}},
        },
    )
    return component, v1, v2


@pytest.fixture
def registry(session) -> ComponentRegistryService:
    return ComponentRegistryService(session)


@pytest.fixture
def service(session) -> CompatibilityService:
    return CompatibilityService(session)


async def test_run_scan_persists_scan_and_changes(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)

    scan = await service.run_scan(project.id, component.id, "1", "2")

    assert scan.id is not None
    assert scan.status == CompatibilityStatus.BREAKING
    assert scan.total_changes == 3
    assert scan.breaking_count == 1
    assert len(scan.changes) == 3

    # Re-fetch from a clean query to prove it was actually written, not
    # just held in the session identity map.
    fetched = await service.get_scan(project.id, scan.id)
    assert fetched.id == scan.id
    assert len(fetched.changes) == 3
    assert fetched.baseline_version_id == v1.id
    assert fetched.candidate_version_id == v2.id


async def test_scan_changes_ordered_by_order_index(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    scan = await service.run_scan(project.id, component.id, "1", "2")

    paths = [c.path for c in scan.changes]
    assert paths == sorted(paths)
    assert [c.order_index for c in scan.changes] == list(range(len(scan.changes)))


async def test_scan_change_jsonb_old_new_values_round_trip(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    scan = await service.run_scan(project.id, component.id, "1", "2")

    added = next(c for c in scan.changes if c.path == "$.input_schema.properties.user_id")
    assert added.old_value is None
    assert added.new_value == {"type": "string"}
    assert added.classification == Classification.BREAKING


async def test_run_scan_with_unknown_component_raises_component_not_found(session, service):
    project = await _make_project(session)
    with pytest.raises(ComponentNotFound):
        await service.run_scan(project.id, uuid.uuid4(), "1", "2")


async def test_run_scan_with_unknown_version_raises_component_version_not_found(
    session, registry, service
):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    with pytest.raises(ComponentVersionNotFound):
        await service.run_scan(project.id, component.id, "1", "does-not-exist")


async def test_scan_from_versions_rejects_unrelated_components(session, registry, service):
    project = await _make_project(session)
    component_a, a_v1, _ = await _make_tool_component(registry, project, slug="tool-a")
    component_b, b_v1, _ = await _make_tool_component(registry, project, slug="tool-b")

    # Directly exercise the defense-in-depth same-component check with two
    # versions belonging to different components (Phase 5 §19) — this
    # cannot happen through the public `run_scan(component_id, ...)` path
    # by construction, but the check still runs every time.
    with pytest.raises(InvalidCompatibilityComparison):
        await service._scan_from_versions(project.id, component_a, a_v1, b_v1)


async def test_comparing_a_version_to_itself_is_zero_changes(session, registry, service):
    project = await _make_project(session)
    component, v1, _ = await _make_tool_component(registry, project)
    scan = await service.run_scan(project.id, component.id, "1", "1")
    assert scan.total_changes == 0
    assert scan.status == CompatibilityStatus.COMPATIBLE


async def test_repeated_scans_create_separate_historical_rows(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    scan_1 = await service.run_scan(project.id, component.id, "1", "2")
    scan_2 = await service.run_scan(project.id, component.id, "1", "2")
    assert scan_1.id != scan_2.id

    result = await service.list_scans(project.id, component_id=component.id)
    assert result.total == 2


async def test_get_scan_404_for_unknown_scan(session, service):
    project = await _make_project(session)
    with pytest.raises(CompatibilityScanNotFound):
        await service.get_scan(project.id, uuid.uuid4())


async def test_cross_project_scan_retrieval_is_rejected(session, registry, service):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    component, v1, v2 = await _make_tool_component(registry, project_a)
    scan = await service.run_scan(project_a.id, component.id, "1", "2")

    with pytest.raises(CompatibilityScanNotFound):
        await service.get_scan(project_b.id, scan.id)


async def test_list_scans_is_project_scoped(session, registry, service):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    component_a, _, _ = await _make_tool_component(registry, project_a, slug="tool-a")
    component_b, _, _ = await _make_tool_component(registry, project_b, slug="tool-b")

    await service.run_scan(project_a.id, component_a.id, "1", "2")
    await service.run_scan(project_b.id, component_b.id, "1", "2")

    result_a = await service.list_scans(project_a.id)
    assert result_a.total == 1
    assert result_a.items[0].component_id == component_a.id


async def test_cross_project_component_comparison_is_rejected(session, registry, service):
    # A component_id from a different project is treated as not found —
    # never leaked across the tenant boundary (mirrors Phase 3/4's
    # tenant-isolation pattern).
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")
    component_b, _, _ = await _make_tool_component(registry, project_b, slug="tool-b")

    with pytest.raises(ComponentNotFound):
        await service.run_scan(project_a.id, component_b.id, "1", "2")


async def test_scan_row_is_immutable_at_the_database_level(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    scan = await service.run_scan(project.id, component.id, "1", "2")
    await session.commit()

    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE compatibility_scans SET status = 'compatible' WHERE id = :id"),
            {"id": scan.id},
        )
    await session.rollback()


async def test_scan_change_row_is_immutable_at_the_database_level(session, registry, service):
    project = await _make_project(session)
    component, v1, v2 = await _make_tool_component(registry, project)
    scan = await service.run_scan(project.id, component.id, "1", "2")
    await session.commit()

    change_id = scan.changes[0].id
    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE scan_changes SET message = 'tampered' WHERE id = :id"),
            {"id": change_id},
        )
    await session.rollback()
