"""Neo4j-backed implementation of the graph repository, plus the abstract
`GraphRepository` Protocol it implements.

All Cypher lives in this module — services never write or see raw Cypher.
Every value (IDs, names, timestamps) is passed as a bound query
parameter; nothing user-controlled is ever interpolated into the query
string. The two things Cypher syntactically cannot parameterize — the
node label and the relationship type — are the only text built into the
query strings themselves, and both are always drawn from closed,
code-defined enums (`ComponentType`'s implicit `Component` label,
`DependencyRelationshipType`'s values), never from a raw client-supplied
string: the API layer accepts relationship type as a Pydantic enum field,
which rejects anything outside this set before it ever reaches this
module. `_rel_type_literal` re-validates that invariant defensively.

The `neo4j` driver package is imported lazily (inside the functions that
actually touch it), not at module level, and `AsyncDriver` is imported
only under `TYPE_CHECKING`. This is deliberate, not stylistic: it lets the
`GraphRepository` Protocol defined in this module — the interface
`DependencyGraphService`/`BlastRadiusService` actually depend on — be
imported and used (with `FakeGraphRepository`, see `tests/fakes.py`)
without the `neo4j` package installed at all. That mattered concretely in
this phase's development environment, where the `neo4j` package could not
be installed (see docs/DECISIONS.md ADR-021): it's what made it possible
to genuinely import and run the BFS/relationship-validation logic in this
module's own test suite, rather than that logic being untestable for the
same reason live Cypher was.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from app.domain.enums import ComponentType, DependencyRelationshipType
from app.domain.exceptions import GraphUnavailable
from app.graph.models import ComponentNode, DependencyEdge

if TYPE_CHECKING:
    from neo4j import AsyncDriver

_LABEL = "Component"


def _rel_type_literal(relationship_type: DependencyRelationshipType) -> str:
    """Return the Cypher-safe literal for a relationship type. Defense in
    depth only: `DependencyRelationshipType` values are already
    hand-written `UPPER_SNAKE_CASE` identifiers with no way for arbitrary
    text to reach this function, but a future enum member that violated
    that shape would fail loudly here instead of producing malformed (or
    unsafe) Cypher."""

    value = relationship_type.value
    if not value.replace("_", "").isalnum() or not value[0].isalpha():
        raise ValueError(f"Unsafe relationship type: {value!r}")  # pragma: no cover
    return value


class GraphRepository(Protocol):
    """The graph operations `DependencyGraphService`/`BlastRadiusService`
    depend on. `Neo4jGraphRepository` below is the real implementation;
    `tests/fakes.py`'s `FakeGraphRepository` implements the same contract
    in-memory so the traversal/business logic in those services is
    unit-testable without a running Neo4j (see docs/DECISIONS.md)."""

    async def upsert_component_node(self, node: ComponentNode) -> None: ...

    async def get_component_node(
        self, project_id: UUID, component_id: UUID
    ) -> ComponentNode | None: ...

    async def delete_component_node(self, project_id: UUID, component_id: UUID) -> None: ...

    async def create_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None: ...

    async def delete_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None: ...

    async def list_direct_dependencies(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]: ...

    async def list_direct_dependents(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]: ...


_UPSERT_NODE_QUERY = f"""
MERGE (c:{_LABEL} {{component_id: $component_id}})
SET c.project_id = $project_id,
    c.organization_id = $organization_id,
    c.component_type = $component_type,
    c.name = $name,
    c.slug = $slug,
    c.version = $version,
    c.checksum = $checksum,
    c.synced_at = $synced_at
"""

_GET_NODE_QUERY = f"""
MATCH (c:{_LABEL} {{component_id: $component_id, project_id: $project_id}})
RETURN c
"""

_DELETE_NODE_QUERY = f"""
MATCH (c:{_LABEL} {{component_id: $component_id, project_id: $project_id}})
DETACH DELETE c
"""

# Direction convention (see docs/DECISIONS.md): an edge points from the
# DEPENDENT to its DEPENDENCY, e.g. (Agent)-[:CALLS]->(Tool). "Direct
# dependencies of X" therefore follows X's outgoing edges.
_LIST_DEPENDENCIES_QUERY = f"""
MATCH (source:{_LABEL} {{component_id: $component_id, project_id: $project_id}})
      -[r]->(target:{_LABEL})
WHERE target.project_id = $project_id
RETURN target.component_id AS component_id,
       target.component_type AS component_type,
       target.name AS name,
       target.slug AS slug,
       type(r) AS relationship_type
"""

# "Direct dependents of X" (who breaks if X changes) follows X's
# *incoming* edges — the opposite direction from dependencies.
_LIST_DEPENDENTS_QUERY = f"""
MATCH (target:{_LABEL} {{component_id: $component_id, project_id: $project_id}})
      <-[r]-(source:{_LABEL})
WHERE source.project_id = $project_id
RETURN source.component_id AS component_id,
       source.component_type AS component_type,
       source.name AS name,
       source.slug AS slug,
       type(r) AS relationship_type
"""

# Idempotent schema initialization — safe to call repeatedly (app startup,
# an explicit admin action). `component_id` gets a uniqueness constraint,
# which Neo4j backs with its own index (covering "PostgreSQL component ID
# lookup" directly); `project_id` and `component_type` get plain indexes
# for tenant-scoped and type-filtered queries.
_SCHEMA_STATEMENTS = (
    f"CREATE CONSTRAINT component_id_unique IF NOT EXISTS "
    f"FOR (c:{_LABEL}) REQUIRE c.component_id IS UNIQUE",
    f"CREATE INDEX component_project_id IF NOT EXISTS FOR (c:{_LABEL}) ON (c.project_id)",
    f"CREATE INDEX component_type_idx IF NOT EXISTS FOR (c:{_LABEL}) ON (c.component_type)",
)


def _record_to_node(node: Any) -> ComponentNode:
    props = dict(node)
    synced_at = props["synced_at"]
    if hasattr(synced_at, "to_native"):
        synced_at = synced_at.to_native()
    return ComponentNode(
        component_id=UUID(props["component_id"]),
        project_id=UUID(props["project_id"]),
        organization_id=UUID(props["organization_id"]),
        component_type=ComponentType(props["component_type"]),
        name=props["name"],
        slug=props["slug"],
        version=props["version"],
        checksum=props["checksum"],
        synced_at=synced_at,
    )


def _record_to_edge(record: dict[str, Any]) -> DependencyEdge:
    return DependencyEdge(
        component_id=UUID(record["component_id"]),
        component_type=ComponentType(record["component_type"]),
        name=record["name"],
        slug=record["slug"],
        relationship_type=DependencyRelationshipType(record["relationship_type"]),
    )


async def initialize_graph_schema(driver: AsyncDriver) -> None:
    from neo4j.exceptions import Neo4jError, ServiceUnavailable

    try:
        for statement in _SCHEMA_STATEMENTS:
            await driver.execute_query(statement)
    except (ServiceUnavailable, Neo4jError) as exc:
        raise GraphUnavailable(str(exc)) from exc


class Neo4jGraphRepository:
    """Real Neo4j-backed `GraphRepository`. Uses the driver's
    `execute_query` (auto-commit, retries transient errors internally)
    rather than hand-managed sessions/transactions — appropriate here
    because every operation is a single, idempotent Cypher statement with
    no cross-statement transactional requirement."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    async def _run(self, query: str, **params: object) -> list[dict[str, Any]]:
        from neo4j.exceptions import Neo4jError, ServiceUnavailable

        from app.observability import start_span

        # spec §17: no official/mature Neo4j auto-instrumentation is
        # relied on here — one manual span per Cypher call, at this
        # single execution boundary every repository method already
        # funnels through. `operation` is just the query's leading
        # clause keyword (e.g. "MERGE", "MATCH") — never the full
        # Cypher text or bound params, which may carry business data.
        operation = query.strip().split(None, 1)[0] if query.strip() else "unknown"
        with start_span(
            "neo4j.query", kind="client", attributes={"agentabi.neo4j_operation": operation}
        ):
            try:
                result = await self._driver.execute_query(query, parameters_=params)
            except (ServiceUnavailable, Neo4jError) as exc:
                raise GraphUnavailable(str(exc)) from exc
            return [record.data() for record in result.records]

    async def upsert_component_node(self, node: ComponentNode) -> None:
        await self._run(
            _UPSERT_NODE_QUERY,
            component_id=str(node.component_id),
            project_id=str(node.project_id),
            organization_id=str(node.organization_id),
            component_type=node.component_type.value,
            name=node.name,
            slug=node.slug,
            version=node.version,
            checksum=node.checksum,
            synced_at=node.synced_at,
        )

    async def get_component_node(
        self, project_id: UUID, component_id: UUID
    ) -> ComponentNode | None:
        records = await self._run(
            _GET_NODE_QUERY, component_id=str(component_id), project_id=str(project_id)
        )
        if not records:
            return None
        return _record_to_node(records[0]["c"])

    async def delete_component_node(self, project_id: UUID, component_id: UUID) -> None:
        await self._run(
            _DELETE_NODE_QUERY, component_id=str(component_id), project_id=str(project_id)
        )

    async def create_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        rel = _rel_type_literal(relationship_type)
        query = f"""
        MATCH (source:{_LABEL} {{component_id: $source_id, project_id: $project_id}})
        MATCH (target:{_LABEL} {{component_id: $target_id, project_id: $project_id}})
        MERGE (source)-[r:{rel}]->(target)
        ON CREATE SET r.created_at = $created_at
        """
        await self._run(
            query,
            source_id=str(source_id),
            target_id=str(target_id),
            project_id=str(project_id),
            created_at=datetime.now(UTC),
        )

    async def delete_dependency(
        self,
        project_id: UUID,
        source_id: UUID,
        target_id: UUID,
        relationship_type: DependencyRelationshipType,
    ) -> None:
        rel = _rel_type_literal(relationship_type)
        query = f"""
        MATCH (source:{_LABEL} {{component_id: $source_id, project_id: $project_id}})
              -[r:{rel}]->
              (target:{_LABEL} {{component_id: $target_id, project_id: $project_id}})
        DELETE r
        """
        await self._run(
            query,
            source_id=str(source_id),
            target_id=str(target_id),
            project_id=str(project_id),
        )

    async def list_direct_dependencies(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]:
        records = await self._run(
            _LIST_DEPENDENCIES_QUERY, component_id=str(component_id), project_id=str(project_id)
        )
        return [_record_to_edge(r) for r in records]

    async def list_direct_dependents(
        self, project_id: UUID, component_id: UUID
    ) -> list[DependencyEdge]:
        records = await self._run(
            _LIST_DEPENDENTS_QUERY, component_id=str(component_id), project_id=str(project_id)
        )
        return [_record_to_edge(r) for r in records]
