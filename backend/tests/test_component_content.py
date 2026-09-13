"""Pure unit tests for type-specific content validation — no database
required."""

import pytest

from app.domain.component_content import validate_content
from app.domain.enums import ComponentType
from app.domain.exceptions import InvalidComponentContent


def test_valid_prompt_content_passes_and_fills_defaults():
    result = validate_content(
        ComponentType.PROMPT, {"template": "Hi {{name}}", "variables": ["name"]}
    )
    assert result["template"] == "Hi {{name}}"
    assert result["settings"] == {}


def test_prompt_content_missing_required_field_rejected():
    with pytest.raises(InvalidComponentContent):
        validate_content(ComponentType.PROMPT, {"variables": ["name"]})


def test_prompt_content_rejects_unknown_fields():
    with pytest.raises(InvalidComponentContent):
        validate_content(ComponentType.PROMPT, {"template": "hi", "unexpected_field": 1})


def test_tool_content_requires_both_schemas():
    result = validate_content(
        ComponentType.TOOL,
        {"input_schema": {"type": "object"}, "output_schema": {"type": "object"}},
    )
    assert result["input_schema"] == {"type": "object"}
    assert result["description"] is None


def test_tool_content_missing_output_schema_rejected():
    with pytest.raises(InvalidComponentContent):
        validate_content(ComponentType.TOOL, {"input_schema": {"type": "object"}})


def test_model_content_valid():
    result = validate_content(
        ComponentType.MODEL,
        {"provider": "openai", "model_identifier": "gpt-5", "parameters": {"temperature": 0.2}},
    )
    assert result["model_identifier"] == "gpt-5"


def test_agent_content_valid():
    result = validate_content(
        ComponentType.AGENT,
        {
            "model_ref": {"slug": "gpt-5", "version": "1"},
            "prompt_ref": {"slug": "greeting", "version": "1"},
            "tools": [{"slug": "search"}],
        },
    )
    assert result["tools"] == [{"slug": "search"}]
    assert result["system_config"] == {}


def test_all_component_types_have_a_registered_content_model():
    # Every ComponentType must validate an empty-required-fields error
    # cleanly (not KeyError) rather than silently accepting anything.
    for component_type in ComponentType:
        with pytest.raises(InvalidComponentContent):
            validate_content(component_type, {"this_field_does_not_exist": True})
