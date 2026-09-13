"""Pure unit tests for `app/trajectory/hashing.py`. No database, no I/O."""

import uuid

from app.trajectory.hashing import compute_event_hash

_TRAJECTORY_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_VERSION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _hash(**overrides):
    kwargs = {
        "trajectory_id": _TRAJECTORY_ID,
        "sequence_number": 5,
        "event_type": "tool_call",
        "component_version_id": _VERSION_ID,
        "input_payload": {"invocation_id": "call-1", "arguments": {"amount": 1}},
        "output_payload": None,
        "error_payload": None,
    }
    kwargs.update(overrides)
    return compute_event_hash(**kwargs)


def test_hash_is_deterministic_for_identical_input():
    assert _hash() == _hash()


def test_hash_is_a_sha256_hex_digest():
    digest = _hash()
    assert len(digest) == 64
    int(digest, 16)  # raises ValueError if not valid hex


def test_hash_changes_when_sequence_number_changes():
    assert _hash(sequence_number=5) != _hash(sequence_number=6)


def test_hash_changes_when_input_payload_changes():
    assert _hash() != _hash(input_payload={"invocation_id": "call-1", "arguments": {"amount": 2}})


def test_hash_changes_when_component_version_changes():
    other_version = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
    assert _hash() != _hash(component_version_id=other_version)


def test_hash_is_insensitive_to_dict_key_order():
    a = compute_event_hash(
        trajectory_id=_TRAJECTORY_ID,
        sequence_number=1,
        event_type="tool_call",
        component_version_id=None,
        input_payload={"b": 2, "a": 1},
        output_payload=None,
        error_payload=None,
    )
    b = compute_event_hash(
        trajectory_id=_TRAJECTORY_ID,
        sequence_number=1,
        event_type="tool_call",
        component_version_id=None,
        input_payload={"a": 1, "b": 2},
        output_payload=None,
        error_payload=None,
    )
    assert a == b


def test_hash_changes_when_trajectory_id_changes():
    other = uuid.UUID("00000000-0000-0000-0000-0000000000d4")
    assert _hash() != _hash(trajectory_id=other)
