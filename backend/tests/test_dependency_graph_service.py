"""`DependencyGraphService` tests.

`sync_component` needs the real Postgres component-registry data (see the
`session` fixture in conftest.py) to read from — that part is a genuine
integration test. Everything downstream of a sync (create/delete
dependency, list dependencies/dependents, validation, tenant isolation)
runs against `FakeGraphRepository`, so those are real unit tests of this
service's own logic, independent of whichever `GraphRepository` backs it.
"""

import uuid

import pytest

from app.domain.enums import ComponentType, DependencyRelationshipType
from app.domain.exceptions import (
    ComponentNotFound,
    GraphComponentNotFound,
    InvalidDependencyRelationship,
)
from app.models import Organization, Project
from app.services.component_registry import ComponentRegistryService
from app.services.dependency_graph import DependencyGraphService
from tests.fakes import FakeGraphRepository


async def _make_project(session, *, org_slug="acme", project_slug="payments") -> Project:
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    return project


async def _make_synced_component(
    service: DependencyGraphService,
    registry: ComponentRegistryService,
    project: Project,
    *,
    component_type: ComponentType,
    slug: str,
):
    component = await registry.create_component(
        project_id=project.id, component_type=component_type, name=slug.title(), slug=slug
    )
    await registry.create_component_version(
        project_id=project.id,
        component_id=component.id,
        version="1",
        content=_content_for(component_type),
    )
    await service.sync_component(project.id, component.id)
    return component


def _content_for(component_type: ComponentType) -> dict[str, object]:
    # Minimal valid content per type-specific validation
    # (`app/domain/component_content.py`), just enough for
    # `create_component_version` not to reject it.
    return {
        ComponentType.AGENT: {"model_ref": {"id": "m1"}, "prompt_ref": {"id": "p1"}},
        ComponentType.PROMPT: {"template": "hello {name}"},
        ComponentType.MODEL: {"provider": "openai", "model_identifier": "gpt-4"},
        ComponentType.PROVIDER: {"provider_type": "openai", "base_url": "https://api.example.com"},
        ComponentType.MCP_SERVER: {"server_name": "srv", "transport": "stdio"},
        ComponentType.TOOL: {"input_schema": {}, "output_schema": {}},
        ComponentType.SCHEMA: {"schema_definition": {"type": "object"}},
        ComponentType.API: {"base_url": "https://api.example.com"},
        ComponentType.WORKFLOW: {"definition": {"steps": []}},
        ComponentType.POLICY: {"rules": {}},
    }[component_type]


@pytest.fixture
def graph() -> FakeGraphRepository:
    return FakeGraphRepository()


@pytest.fixture
def registry(session) -> ComponentRegistryService:
    return ComponentRegistryService(session)


@pytest.fixture
def service(registry, graph) -> DependencyGraphService:
    return DependencyGraphService(registry, graph)


async def test_sync_component_upserts_graph_node(session, service, registry, graph):
    project = await _make_project(session)
    component = await _make_synced_component(
        service, registry, project, component_type=ComponentType.AGENT, slug="support-agent"
    )

    node = await graph.get_component_node(project.id, component.id)
    assert node is not None
    assert node.name == "Support-Agent"
    assert node.version == "1"
    assert node.component_type == ComponentType.AGENT


async def test_sync_component_raises_when_postgres_component_missing(session, service):
    project = await _make_project(session)
    with pytest.raises(ComponentNotFound):
        await service.sync_component(project.id, uuid.uuid4())


async def test_sync_component_is_idempotent(session, service, registry, graph):
    project = await _make_project(session)
    component = await _make_synced_component(
        service, registry, project, component_type=ComponentType.TOOL, slug="calculator"
    )
    node_first = await graph.get_component_node(project.id, component.id)
    await service.sync_component(project.id, component.id)
    node_second = await graph.get_component_node(project.id, component.id)
    assert node_first.component_id == node_second.component_id


async def test_create_dependency_requires_both_nodes_synced(session, service, registry):
    project = await _make_project(session)
    agent = await registry.create_component(
        project_id=project.id, component_type=ComponentType.AGENT, name="A", slug="a"
    )
    await registry.create_component_version(
        project_id=project.id,
        component_id=agent.id,
        version="1",
        content=_content_for(ComponentType.AGENT),
    )
    # Not synced into the graph yet.
    with pytest.raises(GraphComponentNotFound):
        await service.create_dependency(
            project.id, agent.id, uuid.uuid4(), DependencyRelationshipType.CALLS
        )


async def test_create_dependency_rejects_invalid_relationship(session, service, registry):
    project = await _make_project(session)
    agent = await _make_synced_component(
        service, registry, project, component_type=ComponentType.AGENT, slug="agent-a"
    )
    workflow = await _make_synced_component(
        service, registry, project, component_type=ComponentType.WORKFLOW, slug="workflow-a"
    )
    with pytest.raises(InvalidDependencyRelationship):
        await service.create_dependency(
            project.id, agent.id, workflow.id, DependencyRelationshipType.CALLS
        )


async def test_create_and_list_dependency_round_trip(session, service, registry):
    project = await _make_project(session)
    agent = await _make_synced_component(
        service, registry, project, component_type=ComponentType.AGENT, slug="agent-b"
    )
    tool = await _make_synced_component(
        service, registry, project, component_type=ComponentType.TOOL, slug="tool-b"
    )

    await service.create_dependency(project.id, agent.id, tool.id, DependencyRelationshipType.CALLS)

    dependencies = await service.list_dependencies(project.id, agent.id)
    assert len(dependencies) == 1
    assert dependencies[0].component_id == tool.id
    assert dependencies[0].relationship_type == DependencyRelationshipType.CALLS

    dependents = await service.list_dependents(project.id, tool.id)
    assert len(dependents) == 1
    assert dependents[0].component_id == agent.id


async def test_create_dependency_is_idempotent(session, service, registry):
    project = await _make_project(session)
    agent = await _make_synced_component(
        service, registry, project, component_type=ComponentType.AGENT, slug="agent-c"
    )
    tool = await _make_synced_component(
        service, registry, project, component_type=ComponentType.TOOL, slug="tool-c"
    )
    for _ in range(3):
        await service.create_dependency(
            project.id, agent.id, tool.id, DependencyRelationshipType.CALLS
        )
    dependencies = await service.list_dependencies(project.id, agent.id)
    assert len(dependencies) == 1


async def test_delete_dependency_removes_edge_and_is_idempotent(session, service, registry):
    project = await _make_project(session)
    agent = await _make_synced_component(
        service, registry, project, component_type=ComponentType.AGENT, slug="agent-d"
    )
    tool = await _make_synced_component(
        service, registry, project, component_type=ComponentType.TOOL, slug="tool-d"
    )
    await service.create_dependency(project.id, agent.id, tool.id, DependencyRelationshipType.CALLS)
    await service.delete_dependency(project.id, agent.id, tool.id, DependencyRelationshipType.CALLS)
    assert await service.list_dependencies(project.id, agent.id) == []
    # Deleting again is not an error.
    await service.delete_dependency(project.id, agent.id, tool.id, DependencyRelationshipType.CALLS)


async def test_list_dependencies_requires_synced_component(session, service):
    project = await _make_project(session)
    with pytest.raises(GraphComponentNotFound):
        await service.list_dependencies(project.id, uuid.uuid4())


async def test_tenant_isolation_across_projects(session, service, registry):
    project_a = await _make_project(session, org_slug="acme", project_slug="proj-a")
    project_b = await _make_project(session, org_slug="beta", project_slug="proj-b")

    agent_a = await _make_synced_component(
        service, registry, project_a, component_type=ComponentType.AGENT, slug="agent-e"
    )
    tool_a = await _make_synced_component(
        service, registry, project_a, component_type=ComponentType.TOOL, slug="tool-e"
    )
    await service.create_dependency(
        project_a.id, agent_a.id, tool_a.id, DependencyRelationshipType.CALLS
    )

    # The same component_id looked up under a different project is treated
    # as not-synced, even though the id exists in the graph under project_a.
    with pytest.raises(GraphComponentNotFound):
        await service.list_dependencies(project_b.id, agent_a.id)
