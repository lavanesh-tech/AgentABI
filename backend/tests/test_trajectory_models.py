"""Pure unit tests for `app/trajectory/models.py`'s payload dataclasses.
No database, no I/O."""

from app.trajectory.models import (
    ModelRequestPayload,
    ModelResponsePayload,
    StatePayload,
    ToolCallPayload,
    ToolResponsePayload,
)


def test_model_request_payload_to_dict_drops_none_structured_output():
    payload = ModelRequestPayload(messages=[{"role": "user", "content": "hi"}])
    result = payload.to_dict()
    assert result["messages"] == [{"role": "user", "content": "hi"}]
    assert "structured_output" not in result


def test_model_request_payload_keeps_provided_structured_output():
    payload = ModelRequestPayload(messages=[], structured_output={"schema": {"type": "object"}})
    assert payload.to_dict()["structured_output"] == {"schema": {"type": "object"}}


def test_model_response_payload_to_dict():
    payload = ModelResponsePayload(content="hello", finish_reason="stop")
    result = payload.to_dict()
    assert result["content"] == "hello"
    assert result["finish_reason"] == "stop"
    assert "usage" not in result


def test_tool_call_payload_to_dict():
    payload = ToolCallPayload(invocation_id="call-1", arguments={"amount": 1})
    assert payload.to_dict() == {"invocation_id": "call-1", "arguments": {"amount": 1}}


def test_tool_response_payload_input_and_output_dicts():
    payload = ToolResponsePayload(invocation_id="call-1", result={"authorized": True})
    assert payload.to_input_dict() == {"invocation_id": "call-1"}
    assert payload.to_output_dict() == {"result": {"authorized": True}}


def test_tool_response_payload_with_no_result_has_no_output_dict():
    payload = ToolResponsePayload(invocation_id="call-1")
    assert payload.to_output_dict() is None


def test_state_payload_keeps_none_values_distinct_from_absent():
    payload = StatePayload(key="order_status", previous_value=None, current_value="AUTHORIZED")
    result = payload.to_dict()
    assert result["previous_value"] is None
    assert result["current_value"] == "AUTHORIZED"
    assert "scope" not in result


def test_state_payload_includes_scope_when_given():
    payload = StatePayload(key="order_status", scope="order-1", current_value="PAID")
    assert payload.to_dict()["scope"] == "order-1"
