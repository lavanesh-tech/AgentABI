"""Pure unit tests for `app/compatibility/analyzer.py`'s per-component-
type dispatch. No database, no I/O."""

import pytest

from app.compatibility.analyzer import analyze
from app.compatibility.models import ChangeType, Classification, CompatibilityStatus
from app.domain.enums import ComponentType
from app.domain.exceptions import UnsupportedCompatibilityType


def test_provider_is_unsupported():
    with pytest.raises(UnsupportedCompatibilityType):
        analyze(ComponentType.PROVIDER, {}, {})


def test_prompt_content_changed():
    result = analyze(
        ComponentType.PROMPT,
        {"template": "Hello {name}", "variables": ["name"]},
        {"template": "Hi {name}", "variables": ["name"]},
    )
    types = {c.change_type for c in result.changes}
    assert ChangeType.CONTENT_CHANGED in types


def test_prompt_variable_added_is_breaking():
    result = analyze(
        ComponentType.PROMPT,
        {"template": "Hello {name}", "variables": ["name"]},
        {"template": "Hello {name} {age}", "variables": ["name", "age"]},
    )
    change = next(c for c in result.changes if c.change_type == ChangeType.VARIABLE_ADDED)
    assert change.classification == Classification.BREAKING
    assert result.status == CompatibilityStatus.BREAKING


def test_prompt_variable_removed_is_compatible():
    result = analyze(
        ComponentType.PROMPT,
        {"template": "Hello {name} {age}", "variables": ["name", "age"]},
        {"template": "Hello {name}", "variables": ["name"]},
    )
    change = next(c for c in result.changes if c.change_type == ChangeType.VARIABLE_REMOVED)
    assert change.classification == Classification.COMPATIBLE


def test_model_identifier_changed():
    result = analyze(
        ComponentType.MODEL,
        {"provider": "openai", "model_identifier": "gpt-4"},
        {"provider": "openai", "model_identifier": "gpt-4-turbo"},
    )
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.MODEL_IDENTIFIER_CHANGED
    assert result.changes[0].old_value == "gpt-4"
    assert result.changes[0].new_value == "gpt-4-turbo"


def test_model_provider_changed():
    result = analyze(
        ComponentType.MODEL,
        {"provider": "openai", "model_identifier": "gpt-4"},
        {"provider": "google", "model_identifier": "gpt-4"},
    )
    assert any(c.change_type == ChangeType.PROVIDER_CHANGED for c in result.changes)


def test_model_parameter_changed():
    result = analyze(
        ComponentType.MODEL,
        {"provider": "openai", "model_identifier": "gpt-4", "parameters": {"temperature": 0.2}},
        {"provider": "openai", "model_identifier": "gpt-4", "parameters": {"temperature": 0.9}},
    )
    change = next(c for c in result.changes if c.change_type == ChangeType.PARAMETER_CHANGED)
    assert change.path == "$.parameters.temperature"


def test_tool_removed_parameter():
    baseline = {
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["customer_id", "amount"],
        },
        "output_schema": {},
    }
    candidate = {
        "input_schema": {
            "type": "object",
            "properties": {"amount": {"type": "number"}},
            "required": ["amount"],
        },
        "output_schema": {},
    }
    result = analyze(ComponentType.TOOL, baseline, candidate)
    removed = [c for c in result.changes if c.path == "$.input_schema.properties.customer_id"]
    assert len(removed) == 1
    assert removed[0].change_type == ChangeType.REQUIRED_FIELD_REMOVED


def test_tool_added_required_parameter():
    baseline = {
        "input_schema": {
            "type": "object",
            "properties": {"amount": {"type": "number"}},
            "required": ["amount"],
        },
        "output_schema": {},
    }
    candidate = {
        "input_schema": {
            "type": "object",
            "properties": {"amount": {"type": "number"}, "currency": {"type": "string"}},
            "required": ["amount", "currency"],
        },
        "output_schema": {},
    }
    result = analyze(ComponentType.TOOL, baseline, candidate)
    added = next(c for c in result.changes if c.path == "$.input_schema.properties.currency")
    assert added.change_type == ChangeType.REQUIRED_FIELD_ADDED
    assert added.classification == Classification.BREAKING
    assert result.status == CompatibilityStatus.BREAKING


def test_tool_description_changed_is_low_impact():
    result = analyze(
        ComponentType.TOOL,
        {"input_schema": {}, "output_schema": {}, "description": "old"},
        {"input_schema": {}, "output_schema": {}, "description": "new"},
    )
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.DESCRIPTION_CHANGED
    assert result.changes[0].classification == Classification.COMPATIBLE


def test_agent_tool_set_changed():
    result = analyze(
        ComponentType.AGENT,
        {
            "model_ref": {"id": "m1"},
            "prompt_ref": {"id": "p1"},
            "tools": [{"component_id": "t1"}, {"component_id": "t2"}],
        },
        {
            "model_ref": {"id": "m1"},
            "prompt_ref": {"id": "p1"},
            "tools": [{"component_id": "t1"}, {"component_id": "t3"}],
        },
    )
    types_paths = {(c.change_type, c.path) for c in result.changes}
    assert (ChangeType.TOOL_REMOVED, "$.tools.t2") in types_paths
    assert (ChangeType.TOOL_ADDED, "$.tools.t3") in types_paths


def test_agent_model_ref_changed():
    result = analyze(
        ComponentType.AGENT,
        {"model_ref": {"id": "m1"}, "prompt_ref": {"id": "p1"}, "tools": []},
        {"model_ref": {"id": "m2"}, "prompt_ref": {"id": "p1"}, "tools": []},
    )
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.MODEL_REF_CHANGED


def test_workflow_structure_changed_steps():
    result = analyze(
        ComponentType.WORKFLOW,
        {"definition": {"steps": [{"id": "s1", "agent": "a1"}, {"id": "s2", "agent": "a2"}]}},
        {"definition": {"steps": [{"id": "s1", "agent": "a1"}, {"id": "s3", "agent": "a3"}]}},
    )
    types_paths = {(c.change_type, c.path) for c in result.changes}
    assert (ChangeType.STEP_REMOVED, "$.definition.steps.s2") in types_paths
    assert (ChangeType.STEP_ADDED, "$.definition.steps.s3") in types_paths


def test_workflow_required_step_removed():
    result = analyze(
        ComponentType.WORKFLOW,
        {"definition": {"steps": [{"id": "s1", "required": True}]}},
        {"definition": {"steps": []}},
    )
    change = next(c for c in result.changes if c.change_type == ChangeType.REQUIRED_STEP_REMOVED)
    assert change.classification == Classification.BREAKING


def test_workflow_step_order_changed():
    result = analyze(
        ComponentType.WORKFLOW,
        {"definition": {"steps": [{"id": "s1"}, {"id": "s2"}]}},
        {"definition": {"steps": [{"id": "s2"}, {"id": "s1"}]}},
    )
    assert any(c.change_type == ChangeType.STEP_ORDER_CHANGED for c in result.changes)


def test_workflow_without_steps_convention_falls_back_to_generic_diff():
    result = analyze(
        ComponentType.WORKFLOW,
        {"definition": {"mode": "sequential"}},
        {"definition": {"mode": "parallel"}},
    )
    assert len(result.changes) == 1
    assert result.changes[0].path == "$.definition.mode"


def test_policy_rule_changed():
    result = analyze(
        ComponentType.POLICY,
        {"rules": {"max_retries": 3}},
        {"rules": {"max_retries": 5, "allow_pii": True}},
    )
    types_paths = {(c.change_type, c.path) for c in result.changes}
    assert (ChangeType.RULE_CHANGED, "$.rules.max_retries") in types_paths
    assert (ChangeType.RULE_ADDED, "$.rules.allow_pii") in types_paths


def test_mcp_server_config_changed():
    result = analyze(
        ComponentType.MCP_SERVER,
        {"server_name": "srv", "transport": "stdio"},
        {"server_name": "srv", "transport": "sse"},
    )
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.TRANSPORT_CHANGED


def test_api_method_changed_is_breaking():
    result = analyze(
        ComponentType.API,
        {"base_url": "https://x.example.com", "method": "GET"},
        {"base_url": "https://x.example.com", "method": "POST"},
    )
    assert len(result.changes) == 1
    assert result.changes[0].change_type == ChangeType.METHOD_CHANGED
    assert result.changes[0].classification == Classification.BREAKING


def test_schema_component_type_uses_neutral_direction():
    result = analyze(
        ComponentType.SCHEMA,
        {
            "schema_definition": {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            }
        },
        {"schema_definition": {"type": "object", "properties": {}, "required": []}},
    )
    change = next(c for c in result.changes if c.change_type == ChangeType.REQUIRED_FIELD_REMOVED)
    # NEUTRAL reading is more conservative than INPUT's COMPATIBLE verdict
    # for the same structural change.
    assert change.classification == Classification.POTENTIALLY_BREAKING


def test_identical_content_is_zero_changes_compatible_status():
    content = {"provider": "openai", "model_identifier": "gpt-4", "parameters": {}}
    result = analyze(ComponentType.MODEL, content, dict(content))
    assert result.total_changes == 0
    assert result.status == CompatibilityStatus.COMPATIBLE
