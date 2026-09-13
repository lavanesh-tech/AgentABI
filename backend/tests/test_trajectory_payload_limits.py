"""Pure unit tests for `app/trajectory/payload_limits.py`. No database,
no I/O."""

import pytest

from app.domain.exceptions import TrajectoryPayloadTooLarge
from app.trajectory.payload_limits import canonical_size_bytes, enforce_payload_limit


def test_none_passes_through_untouched():
    value, truncated, original_size = enforce_payload_limit(None, field_name="input")
    assert value is None
    assert truncated is False
    assert original_size is None


def test_small_payload_is_stored_in_full():
    payload = {"customer_id": "991", "amount": 125.0}
    value, truncated, original_size = enforce_payload_limit(payload, field_name="input")
    assert value == payload
    assert truncated is False
    assert original_size is None


def test_payload_between_soft_and_hard_limit_is_truncated():
    payload = {"blob": "x" * 100}
    value, truncated, original_size = enforce_payload_limit(
        payload, field_name="input", soft_limit_bytes=10, hard_limit_bytes=10_000
    )
    assert truncated is True
    assert original_size is not None
    assert original_size > 10
    assert value["_truncated"] is True
    assert value["_original_size_bytes"] == original_size
    assert "_preview" in value


def test_payload_over_hard_limit_is_rejected():
    payload = {"blob": "x" * 1000}
    with pytest.raises(TrajectoryPayloadTooLarge) as exc_info:
        enforce_payload_limit(
            payload, field_name="input", soft_limit_bytes=10, hard_limit_bytes=100
        )
    assert exc_info.value.field_name == "input"
    assert exc_info.value.size_bytes > 100
    assert exc_info.value.limit_bytes == 100


def test_canonical_size_is_deterministic():
    payload = {"b": 2, "a": 1}
    assert canonical_size_bytes(payload) == canonical_size_bytes({"a": 1, "b": 2})


def test_enforcement_is_deterministic_across_calls():
    payload = {"blob": "y" * 100}
    first = enforce_payload_limit(
        payload, field_name="input", soft_limit_bytes=10, hard_limit_bytes=10_000
    )
    second = enforce_payload_limit(
        payload, field_name="input", soft_limit_bytes=10, hard_limit_bytes=10_000
    )
    assert first == second
