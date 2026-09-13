"""Which (source_type, relationship_type, target_type) triples are
semantically valid dependency edges.

Centralized here so the rule "a Model can't CALL a Workflow" lives in
exactly one place, checked before any write reaches Neo4j — not scattered
across API routes or repeated in every service method.
"""

from app.domain.enums import ComponentType, DependencyRelationshipType
from app.domain.exceptions import InvalidDependencyRelationship

CT = ComponentType
RT = DependencyRelationshipType

# (source component_type, relationship_type, target component_type)
_ALLOWED_RELATIONSHIPS: frozenset[
    tuple[ComponentType, DependencyRelationshipType, ComponentType]
] = frozenset(
    {
        (CT.AGENT, RT.USES_MODEL, CT.MODEL),
        (CT.AGENT, RT.USES_PROMPT, CT.PROMPT),
        (CT.AGENT, RT.CALLS, CT.TOOL),
        (CT.TOOL, RT.BELONGS_TO, CT.MCP_SERVER),
        (CT.TOOL, RT.USES_SCHEMA, CT.SCHEMA),
        (CT.TOOL, RT.CALLS_API, CT.API),
        (CT.WORKFLOW, RT.CONTAINS, CT.AGENT),
        (CT.AGENT, RT.DEPENDS_ON, CT.AGENT),
        (CT.POLICY, RT.APPLIES_TO, CT.AGENT),
        (CT.MODEL, RT.PROVIDED_BY, CT.PROVIDER),
    }
)


def is_relationship_allowed(
    source_type: ComponentType,
    relationship_type: DependencyRelationshipType,
    target_type: ComponentType,
) -> bool:
    return (source_type, relationship_type, target_type) in _ALLOWED_RELATIONSHIPS


def validate_relationship(
    source_type: ComponentType,
    relationship_type: DependencyRelationshipType,
    target_type: ComponentType,
) -> None:
    """Raises `InvalidDependencyRelationship` if this triple isn't one of
    the allowed shapes. Called by `DependencyGraphService` before any
    Neo4j write."""

    if not is_relationship_allowed(source_type, relationship_type, target_type):
        raise InvalidDependencyRelationship(source_type, relationship_type, target_type)
