"""DependencyGraphService — the only place that moves component identity
from PostgreSQL into Neo4j and manages dependency edges between synced
nodes. API routes call this service; they never touch `GraphRepository`
or Cypher directly.

Synchronization is synchronous and service-driven (call `sync_component`
whenever a caller wants a component's current identity reflected in the
graph) — not an async/queued pipeline. Kafka-based event-driven sync is
explicitly out of scope for Phase 4 (see docs/ROADMAP.md, Phase 13).
"""

import uuid
from datetime import UTC, datetime

from app.domain.enums import DependencyRelationshipType
from app.domain.exceptions import GraphComponentNotFound
from app.domain.relationship_rules import validate_relationship
from app.graph.models import ComponentNode, DependencyEdge
from app.graph.repository import GraphRepository
from app.services.component_registry import ComponentRegistryService


class DependencyGraphService:
    """Bridges the PostgreSQL component registry (Phase 3) and the Neo4j
    dependency graph (Phase 4). Holds two collaborators rather than one:
    `ComponentRegistryService` for the Postgres-side source of truth
    (existence, tenant ownership, current version/checksum), and
    `GraphRepository` for the graph itself.
    """

    def __init__(self, registry: ComponentRegistryService, graph: GraphRepository) -> None:
        self._registry = registry
        self._graph = graph

    async def sync_component(self, project_id: uuid.UUID, component_id: uuid.UUID) -> ComponentNode:
        """Upsert a component's current identity into the graph.

        PostgreSQL stays authoritative: this reads the component and its
        latest version from Postgres (raising the ordinary Phase 3
        `ComponentNotFound`/`ComponentVersionNotFound` if either is
        missing) and writes a `Component` node carrying just enough
        identity to be looked up and displayed — never the JSONB content
        payload itself.
        """

        component = await self._registry.get_component(project_id, component_id)
        latest_version = await self._registry.get_latest_component_version(project_id, component_id)
        node = ComponentNode(
            component_id=component.id,
            project_id=component.project_id,
            organization_id=component.organization_id,
            component_type=component.component_type,
            name=component.name,
            slug=component.slug,
            version=latest_version.version,
            checksum=latest_version.checksum,
            synced_at=datetime.now(UTC),
        )
        await self._graph.upsert_component_node(node)
        return node

    async def _require_graph_node(
        self, project_id: uuid.UUID, component_id: uuid.UUID
    ) -> ComponentNode:
        node = await self._graph.get_component_node(project_id, component_id)
        if node is None:
            raise GraphComponentNotFound(component_id)
        return node

    async def create_dependency(
        self,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        """Create (idempotently — `MERGE`) a dependency edge from
        `source_id` to `target_id`. Both components must already be
        synced into the graph (`GraphComponentNotFound` otherwise), and
        the (source_type, relationship_type, target_type) triple must be
        one `app/domain/relationship_rules.py` allows.
        """

        source = await self._require_graph_node(project_id, source_id)
        target = await self._require_graph_node(project_id, target_id)
        validate_relationship(source.component_type, relationship_type, target.component_type)
        await self._graph.create_dependency(project_id, source_id, target_id, relationship_type)

    async def delete_dependency(
        self,
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        """Delete a dependency edge. Idempotent: deleting an edge that
        doesn't exist is not an error — the end state (no such edge) is
        what the caller asked for either way.
        """

        await self._require_graph_node(project_id, source_id)
        await self._require_graph_node(project_id, target_id)
        await self._graph.delete_dependency(project_id, source_id, target_id, relationship_type)

    async def list_dependencies(
        self, project_id: uuid.UUID, component_id: uuid.UUID
    ) -> list[DependencyEdge]:
        """Direct dependencies of `component_id` — what it depends ON
        (its outgoing edges; see the direction convention documented on
        `DependencyRelationshipType`)."""

        await self._require_graph_node(project_id, component_id)
        return await self._graph.list_direct_dependencies(project_id, component_id)

    async def list_dependents(
        self, project_id: uuid.UUID, component_id: uuid.UUID
    ) -> list[DependencyEdge]:
        """Direct dependents of `component_id` — what depends ON it (its
        incoming edges): who breaks if `component_id` changes."""

        await self._require_graph_node(project_id, component_id)
        return await self._graph.list_direct_dependents(project_id, component_id)
