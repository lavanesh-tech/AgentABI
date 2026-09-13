"""Type-specific content validation for component versions.

Every `ComponentType` has a Pydantic model describing its expected content
shape (§5 of the project spec). `validate_content` is the single entry
point the service layer calls: it looks up the model for the given
`ComponentType`, validates the raw dict against it (rejecting unknown
fields), and returns a canonical plain dict ready for checksum computation
and JSONB storage. This is what stands between "PostgreSQL JSONB accepts
anything" and "known component types can't store garbage."
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.domain.enums import ComponentType
from app.domain.exceptions import InvalidComponentContent


class _StrictContent(BaseModel):
    """Base for all content models: unknown fields are rejected rather
    than silently dropped or stored, so a typo in a request never produces
    a version that quietly ignores what the caller sent."""

    model_config = ConfigDict(extra="forbid")


class PromptContent(_StrictContent):
    template: str
    variables: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)


class ModelContent(_StrictContent):
    provider: str
    model_identifier: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ProviderContent(_StrictContent):
    provider_type: str
    base_url: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class MCPServerContent(_StrictContent):
    server_name: str
    transport: str
    endpoint: str | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ToolContent(_StrictContent):
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    description: str | None = None


class SchemaContent(_StrictContent):
    schema_definition: dict[str, Any]
    schema_format: str = "json-schema"


class APIContent(_StrictContent):
    base_url: str
    method: str = "GET"
    auth: dict[str, Any] = Field(default_factory=dict)


class WorkflowContent(_StrictContent):
    definition: dict[str, Any]


class PolicyContent(_StrictContent):
    rules: dict[str, Any]


class AgentContent(_StrictContent):
    model_ref: dict[str, Any]
    prompt_ref: dict[str, Any]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    system_config: dict[str, Any] = Field(default_factory=dict)


_CONTENT_MODELS: dict[ComponentType, type[_StrictContent]] = {
    ComponentType.AGENT: AgentContent,
    ComponentType.PROMPT: PromptContent,
    ComponentType.MODEL: ModelContent,
    ComponentType.PROVIDER: ProviderContent,
    ComponentType.MCP_SERVER: MCPServerContent,
    ComponentType.TOOL: ToolContent,
    ComponentType.SCHEMA: SchemaContent,
    ComponentType.API: APIContent,
    ComponentType.WORKFLOW: WorkflowContent,
    ComponentType.POLICY: PolicyContent,
}


def validate_content(component_type: ComponentType, raw_content: dict[str, Any]) -> dict[str, Any]:
    """Validate `raw_content` against the model registered for
    `component_type`. Returns a canonical plain dict on success; raises
    `InvalidComponentContent` on failure."""

    model_cls = _CONTENT_MODELS[component_type]
    try:
        validated = model_cls.model_validate(raw_content)
    except ValidationError as exc:
        raise InvalidComponentContent(component_type, str(exc)) from exc
    return validated.model_dump(mode="json")
