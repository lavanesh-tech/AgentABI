"""In-memory `GraphRepository` implementation used to unit-test
`DependencyGraphService`/`BlastRadiusService` business logic (validation,
BFS traversal, cycle handling, tenant isolation) without a running Neo4j.

Deliberately re-implements the same semantics as `Neo4jGraphRepository`
(idempotent upsert/create, tenant-scoped lookups) using plain Python dicts
— not a mock or a stub that just records calls, but a real, working graph
so the tests exercising it are exercising real behavior, not assertions
about which methods were invoked. See docs/DECISIONS.md for why the
traversal algorithm's tests can be genuine unit tests even though a real
Neo4j instance was not obtainable in this environment (Phase 4).
"""

from dataclasses import replace
from uuid import UUID

from app.domain.enums import DependencyRelationshipType
from app.graph.models import ComponentNode, DependencyEdge


class FakeGraphRepository:
    def __init__(self) -> None:
        self._nodes: dict[UUID, ComponentNode] = {}
        # (project_id, source_id, target_id, relationship_type) -> None
        self._edges: set[tuple[UUID, UUID, UUID, DependencyRelationshipType]] = set()

    async def upsert_component_node(self, node: ComponentNode) -> None:
        self._nodes[node.component_id] = replace(node)

    async def get_component_node(
        self, project_id: UUID, component_id: UUID
    ) -> ComponentNode | None:
        node = self._nodes.get(component_id)
        if node is None or node.project_id != project_id:
            return None
        return node

    async def delete_component_node(self, project_id: UUID, component_id: UUID) -> None:
        node = self._nodes.get(component_id)
        if node is None or node.project_id != project_id:
            return
        del self._nodes[component_id]
        self._edges = {
            edge for edge in self._edges if edge[1] != component_id and edge[2] != component_id
        }

    async def create_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        # MERGE semantics: adding the same edge twice is a no-op, matching
        # `Neo4jGraphRepository.create_dependency`'s idempotency.
        self._edges.add((project_id, source_id, target_id, relationship_type))

    async def delete_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        self._edges.discard((project_id, source_id, target_id, relationship_type))

    async def list_direct_dependencies(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]:
        results = []
        for edge_project_id, source_id, target_id, rel in self._edges:
            if edge_project_id != project_id or source_id != component_id:
                continue
            target = self._nodes.get(target_id)
            if target is None or target.project_id != project_id:
                continue
            results.append(
                DependencyEdge(
                    component_id=target.component_id,
                    component_type=target.component_type,
                    name=target.name,
                    slug=target.slug,
                    relationship_type=rel,
                )
            )
        return results

    async def list_direct_dependents(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]:
        results = []
        for edge_project_id, source_id, target_id, rel in self._edges:
            if edge_project_id != project_id or target_id != component_id:
                continue
            source = self._nodes.get(source_id)
            if source is None or source.project_id != project_id:
                continue
            results.append(
                DependencyEdge(
                    component_id=source.component_id,
                    component_type=source.component_type,
                    name=source.name,
                    slug=source.slug,
                    relationship_type=rel,
                )
            )
        return results
