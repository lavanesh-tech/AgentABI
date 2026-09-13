"""`BlastRadiusService` unit tests — pure Python BFS over
`FakeGraphRepository`, with explicit cyclic-graph coverage per the Phase 4
spec's mandate that cycle handling be tested, not just implemented."""

import uuid
from datetime import UTC, datetime

import pytest

from app.domain.enums import ComponentType, DependencyRelationshipType
from app.domain.exceptions import GraphComponentNotFound
from app.graph.models import ComponentNode
from app.services.blast_radius import BlastRadiusService
from tests.fakes import FakeGraphRepository


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


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def graph() -> FakeGraphRepository:
    return FakeGraphRepository()


@pytest.fixture
def service(graph) -> BlastRadiusService:
    return BlastRadiusService(graph)


async def _link(graph, project_id, source, target, rel=DependencyRelationshipType.CALLS):
    await graph.upsert_component_node(source)
    await graph.upsert_component_node(target)
    await graph.create_dependency(project_id, source.component_id, target.component_id, rel)


async def test_blast_radius_raises_for_unsynced_component(service, project_id):
    with pytest.raises(GraphComponentNotFound):
        await service.compute(project_id, uuid.uuid4())


async def test_blast_radius_of_leaf_component_is_empty(service, graph, project_id):
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await graph.upsert_component_node(tool)
    result = await service.compute(project_id, tool.component_id)
    assert result.direct_dependents == ()
    assert result.transitive_dependents == ()
    assert result.total_affected == 0


async def test_direct_dependents_only(service, graph, project_id):
    # Agent -[CALLS]-> Tool: Tool's dependents include Agent.
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, agent, tool)

    result = await service.compute(project_id, tool.component_id)
    assert len(result.direct_dependents) == 1
    assert result.direct_dependents[0].component_id == agent.component_id
    assert result.direct_dependents[0].depth == 1


async def test_transitive_dependents_multiple_hops(service, graph, project_id):
    # Workflow -[CONTAINS]-> Agent -[CALLS]-> Tool
    # Blast radius of Tool includes Agent (direct) and Workflow (transitive).
    workflow = _node(project_id, ComponentType.WORKFLOW, "Workflow")
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, workflow, agent, DependencyRelationshipType.CONTAINS)
    await _link(graph, project_id, agent, tool, DependencyRelationshipType.CALLS)

    result = await service.compute(project_id, tool.component_id)
    ids = {e.component_id for e in result.transitive_dependents}
    assert ids == {agent.component_id, workflow.component_id}

    direct_ids = {e.component_id for e in result.direct_dependents}
    assert direct_ids == {agent.component_id}

    workflow_entry = next(
        e for e in result.transitive_dependents if e.component_id == workflow.component_id
    )
    assert workflow_entry.depth == 2
    assert workflow_entry.path == (tool.component_id, agent.component_id, workflow.component_id)


async def test_cycle_terminates_and_deduplicates(service, graph, project_id):
    # A -[DEPENDS_ON]-> B -[DEPENDS_ON]-> C -[DEPENDS_ON]-> A (a cycle).
    a = _node(project_id, ComponentType.AGENT, "A")
    b = _node(project_id, ComponentType.AGENT, "B")
    c = _node(project_id, ComponentType.AGENT, "C")
    await _link(graph, project_id, a, b, DependencyRelationshipType.DEPENDS_ON)
    await _link(graph, project_id, b, c, DependencyRelationshipType.DEPENDS_ON)
    await _link(graph, project_id, c, a, DependencyRelationshipType.DEPENDS_ON)

    result = await service.compute(project_id, a.component_id, max_depth=10)

    # Every other node in the cycle is reached exactly once, and the
    # traversal terminates (does not hang / raise from unbounded
    # recursion) despite the cycle looping back to the start.
    ids = [e.component_id for e in result.transitive_dependents]
    assert sorted(ids) == sorted([b.component_id, c.component_id])
    assert len(ids) == len(set(ids))  # no duplicates


async def test_max_depth_cuts_off_traversal(service, graph, project_id):
    workflow = _node(project_id, ComponentType.WORKFLOW, "Workflow")
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, workflow, agent, DependencyRelationshipType.CONTAINS)
    await _link(graph, project_id, agent, tool, DependencyRelationshipType.CALLS)

    result = await service.compute(project_id, tool.component_id, max_depth=1)
    ids = {e.component_id for e in result.transitive_dependents}
    assert ids == {agent.component_id}  # workflow is at depth 2, excluded


async def test_affected_by_type_groups_entries(service, graph, project_id):
    workflow = _node(project_id, ComponentType.WORKFLOW, "Workflow")
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, workflow, agent, DependencyRelationshipType.CONTAINS)
    await _link(graph, project_id, agent, tool, DependencyRelationshipType.CALLS)

    result = await service.compute(project_id, tool.component_id)
    assert {e.component_id for e in result.affected_by_type[ComponentType.AGENT]} == {
        agent.component_id
    }
    assert {e.component_id for e in result.affected_by_type[ComponentType.WORKFLOW]} == {
        workflow.component_id
    }


async def test_deterministic_ordering_across_repeated_calls(service, graph, project_id):
    agent1 = _node(project_id, ComponentType.AGENT, "Agent1")
    agent2 = _node(project_id, ComponentType.AGENT, "Agent2")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, agent1, tool)
    await _link(graph, project_id, agent2, tool)

    result_a = await service.compute(project_id, tool.component_id)
    result_b = await service.compute(project_id, tool.component_id)
    order_a = [e.component_id for e in result_a.transitive_dependents]
    order_b = [e.component_id for e in result_b.transitive_dependents]
    assert order_a == order_b == sorted(order_a)


async def test_max_depth_must_be_at_least_one(service, graph, project_id):
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await graph.upsert_component_node(tool)
    with pytest.raises(ValueError):
        await service.compute(project_id, tool.component_id, max_depth=0)


async def test_tenant_isolation_in_blast_radius(service, graph, project_id):
    other_project_id = uuid.uuid4()
    agent = _node(project_id, ComponentType.AGENT, "Agent")
    tool = _node(project_id, ComponentType.TOOL, "Tool")
    await _link(graph, project_id, agent, tool)

    with pytest.raises(GraphComponentNotFound):
        await service.compute(other_project_id, tool.component_id)
