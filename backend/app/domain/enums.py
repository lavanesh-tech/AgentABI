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
