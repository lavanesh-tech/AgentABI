"""Strongly-typed enums shared by the domain layer. Kept separate from
`app.models` so service/domain code can reference a component type without
importing SQLAlchemy."""

import enum


class ComponentType(enum.StrEnum):
    """The kinds of system component AgentABI tracks. Phase 3 registers and
    versions these; Phase 4 syncs them into the Neo4j dependency graph."""

    AGENT = "agent"
    PROMPT = "prompt"
    MODEL = "model"
    PROVIDER = "provider"
    MCP_SERVER = "mcp_server"
    TOOL = "tool"
    SCHEMA = "schema"
    API = "api"
    WORKFLOW = "workflow"
    POLICY = "policy"


class ComponentStatus(enum.StrEnum):
    """Lifecycle status of a component's *identity* — distinct from a
    version's immutability. A component stays ACTIVE while gaining new
    versions, then DEPRECATED/ARCHIVED once retired. "Active/production
    version" (which specific version is deployed) is a later-phase
    concept, not this."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class DependencyRelationshipType(enum.StrEnum):
    """Neo4j relationship types connecting two `Component` nodes.

    The enum *value* is the exact literal used in Cypher (e.g.
    `-[:USES_MODEL]->`). Because relationship types can't be parameterized
    in Cypher, `app/graph/repository.py` embeds this value directly into
    query text — safe only because it always comes from this closed,
    code-defined enum, never from a raw client-supplied string (the API
    layer accepts it as a Pydantic enum field, which rejects anything not
    in this set before it reaches the graph layer).

    Direction convention (see docs/DECISIONS.md): every relationship
    points from the DEPENDENT to its DEPENDENCY — `(Agent)-[:CALLS]->(Tool)`
    reads "Agent depends on Tool, i.e. Agent calls Tool." If Tool changes,
    Agent (the source of the edge) is affected. "Who depends on X" is
    therefore found by following edges *into* X, not out of it.
    """

    USES_MODEL = "USES_MODEL"
    USES_PROMPT = "USES_PROMPT"
    CALLS = "CALLS"
    BELONGS_TO = "BELONGS_TO"
    USES_SCHEMA = "USES_SCHEMA"
    CALLS_API = "CALLS_API"
    CONTAINS = "CONTAINS"
    DEPENDS_ON = "DEPENDS_ON"
    APPLIES_TO = "APPLIES_TO"
    PROVIDED_BY = "PROVIDED_BY"
