"""Pure unit tests for `app/trajectory/validation.py`. No database, no
I/O."""

import pytest

from app.domain.exceptions import InvalidTrajectoryEvent
from app.trajectory.models import EventType
from app.trajectory.validation import validate_event_shape


def test_run_completed_is_reserved():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.RUN_COMPLETED, input_payload=None, error_payload=None)


def test_run_failed_is_reserved():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.RUN_FAILED, input_payload=None, error_payload=None)


def test_tool_call_requires_invocation_id():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(
            EventType.TOOL_CALL, input_payload={"arguments": {}}, error_payload=None
        )


def test_tool_call_with_invocation_id_is_valid():
    validate_event_shape(
        EventType.TOOL_CALL, input_payload={"invocation_id": "call-1"}, error_payload=None
    )


def test_tool_response_requires_invocation_id():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.TOOL_RESPONSE, input_payload={}, error_payload=None)


def test_tool_response_with_invocation_id_is_valid():
    validate_event_shape(
        EventType.TOOL_RESPONSE, input_payload={"invocation_id": "call-1"}, error_payload=None
    )


def test_state_read_requires_key():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.STATE_READ, input_payload={}, error_payload=None)


def test_state_write_requires_key():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.STATE_WRITE, input_payload=None, error_payload=None)


def test_state_write_with_key_is_valid():
    validate_event_shape(
        EventType.STATE_WRITE, input_payload={"key": "order_status"}, error_payload=None
    )


def test_error_event_requires_error_payload():
    with pytest.raises(InvalidTrajectoryEvent):
        validate_event_shape(EventType.ERROR, input_payload=None, error_payload=None)


def test_error_event_with_error_payload_is_valid():
    validate_event_shape(EventType.ERROR, input_payload=None, error_payload={"message": "boom"})


def test_unconstrained_event_types_accept_any_payload():
    validate_event_shape(EventType.RUN_STARTED, input_payload=None, error_payload=None)
    validate_event_shape(EventType.AGENT_STARTED, input_payload=None, error_payload=None)
    validate_event_shape(
        EventType.MODEL_REQUEST, input_payload={"messages": []}, error_payload=None
    )
    validate_event_shape(EventType.STRUCTURED_OUTPUT, input_payload=None, error_payload=None)
