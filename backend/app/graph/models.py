"""Plain data shapes the graph layer speaks in — never raw Neo4j `Record`/
`Node` objects, and never SQLAlchemy ORM models. `ComponentNode` is the
graph's copy of a component's identity (PostgreSQL stays authoritative for
everything else — see docs/ARCHITECTURE.md's Phase 4 section); the JSONB
`content` payload is deliberately not duplicated here.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.enums import ComponentType, DependencyRelationshipType


@dataclass(frozen=True, slots=True)
class ComponentNode:
    component_id: UUID
    project_id: UUID
    organization_id: UUID
    component_type: ComponentType
    name: str
    slug: str
    version: str
    checksum: str
    synced_at: datetime


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    """One end of a dependency relationship as seen from the other end —
    e.g. `list_direct_dependents(tool_id)` returns one `DependencyEdge` per
    component that depends on `tool_id`, carrying just enough of that
    component's identity to display or chain into another lookup."""

    component_id: UUID
    component_type: ComponentType
    name: str
    slug: str
    relationship_type: DependencyRelationshipType
