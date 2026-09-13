"""Integration tests for `Neo4jGraphRepository` against a REAL Neo4j
instance.

These are skipped (not faked, not mocked into passing) whenever Neo4j
isn't reachable — see docs/DECISIONS.md's "Neo4j verification" section for
exactly what was attempted in this development environment (a Mac
device-bridge VM with no Docker, and a cloud sandbox whose Docker daemon
can run but whose registry pulls are blocked) and the exact commands to
run this suite for real once Neo4j is reachable:

    docker compose -f infra/docker-compose.yml up -d neo4j
    cd backend && pytest tests/test_graph_repository.py -v

Every test here talks to the real driver and real Cypher — nothing in
this file is a mock.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from neo4j import AsyncGraphDatabase

from app.core.config import get_settings
from app.domain.enums import ComponentType, DependencyRelationshipType
from app.graph.models import ComponentNode
from app.graph.repository import Neo4jGraphRepository, initialize_graph_schema


async def _neo4j_reachable() -> bool:
    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        await driver.verify_connectivity()
        return True
    except Exception:
        return False
    finally:
        await driver.close()


@pytest.fixture
async def real_driver():
    if not await _neo4j_reachable():
        pytest.skip(
            "Neo4j is not reachable at the configured NEO4J_URI in this environment "
            "(see docs/DECISIONS.md for what was attempted and how to run this suite "
            "for real). This is a genuine skip, not a fabricated pass."
        )
    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    await initialize_graph_schema(driver)
    yield driver
    # Test isolation: wipe everything this suite might have written.
    await driver.execute_query("MATCH (n:Component) DETACH DELETE n")
    await driver.close()


@pytest.fixture
def repo(real_driver) -> Neo4jGraphRepository:
    return Neo4jGraphRepository(real_driver)


def _node(project_id: uuid.UUID, component_type: ComponentType, name: str) -> ComponentNode:
    return ComponentNode(
        component_id=uuid.uuid4(),
        project_id=project_id,
        organization_id=uuid.uuid4(),
        component_type=component_type,
        name=name,
        slug=name.lower(),
        version="1",
        checksum="deadbeef",
        synced_at=datetime.now(UTC),
    )


async def test_schema_initialization_is_idempotent(real_driver):
    await initialize_graph_schema(real_driver)
    await initialize_graph_schema(real_driver)


async def test_upsert_and_get_component_node(repo):
    project_id = uuid.uuid4()
    node = _node(project_id, ComponentType.AGENT, "Agent")
    await repo.upsert_component_node(node)

    fetched = await repo.get_component_node(project_id, node.component_id)
    assert fetched is not None
    assert fetched.component_id == node.component_id
    assert fetched.name == "Agent"
    assert fetched.component_type == ComponentType.AGENT


async def test_upsert_is_idempotent_and_updates_fields(repo):
    project_id = uuid.uuid4()
    node = _node(project_id, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(node)
    updated = replace(node, version="2", checksum="cafebabe")
    await repo.upsert_component_node(updated)

    fetched = await repo.get_component_node(project_id, node.component_id)
    assert fetched.version == "2"
    assert fetched.checksum == "cafebabe"


async def test_get_component_node_returns_none_when_missing(repo):
    assert await repo.get_component_node(uuid.uuid4(), uuid.uuid4()) is None


async def test_get_component_node_is_tenant_scoped(repo):
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    node = _node(project_a, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(node)
    assert await repo.get_component_node(project_b, node.component_id) is None


async def test_delete_component_node_removes_it_and_its_edges(repo):
    project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(agent)
    await repo.upsert_component_node(tool)
    await repo.create_dependency(
        project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
    )

    await repo.delete_component_node(project_id, tool.component_id)

    assert await repo.get_component_node(project_id, tool.component_id) is None
    assert await repo.list_direct_dependencies(project_id, agent.component_id) == []


async def test_create_dependency_and_list_direction(repo):
    project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(agent)
    await repo.upsert_component_node(tool)

    await repo.create_dependency(
        project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
    )

    dependencies = await repo.list_direct_dependencies(project_id, agent.component_id)
    assert len(dependencies) == 1
    assert dependencies[0].component_id == tool.component_id

    dependents = await repo.list_direct_dependents(project_id, tool.component_id)
    assert len(dependents) == 1
    assert dependents[0].component_id == agent.component_id

    # Direction is not symmetric.
    assert await repo.list_direct_dependents(project_id, agent.component_id) == []
    assert await repo.list_direct_dependencies(project_id, tool.component_id) == []


async def test_create_dependency_is_idempotent_merge(repo):
    project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(agent)
    await repo.upsert_component_node(tool)

    for _ in range(3):
        await repo.create_dependency(
            project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
        )

    dependencies = await repo.list_direct_dependencies(project_id, agent.component_id)
    assert len(dependencies) == 1


async def test_delete_dependency_removes_only_that_edge(repo):
    project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    model = _node(project_id, ComponentType.MODEL, "Model")
    await repo.upsert_component_node(agent)
    await repo.upsert_component_node(tool)
    await repo.upsert_component_node(model)
    await repo.create_dependency(
        project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
    )
    await repo.create_dependency(
        project_id, agent.component_id, model.component_id, DependencyRelationshipType.USES_MODEL
    )

    await repo.delete_dependency(
        project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
    )

    dependencies = await repo.list_direct_dependencies(project_id, agent.component_id)
    assert len(dependencies) == 1
    assert dependencies[0].component_id == model.component_id


async def test_delete_dependency_on_nonexistent_edge_is_a_noop(repo):
    project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await repo.upsert_component_node(agent)
    await repo.upsert_component_node(tool)
    # No edge was ever created — deleting it must not raise.
    await repo.delete_dependency(
        project_id, agent.component_id, tool.component_id, DependencyRelationshipType.CALLS
    )
