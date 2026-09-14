"""Pure unit tests for `app/events/envelope.py` (Phase 13 spec §5/§6/
§23/§35). No SQLAlchemy/FastAPI/aiokafka import there, so this runs for
real via `pytest --noconftest`.
"""

import dataclasses
import uuid

import pytest

from app.events.envelope import (
    EVENT_TYPE_ANALYSIS_COMPLETED,
    EVENT_TYPE_ANALYSIS_FAILED,
    EVENT_TYPE_ANALYSIS_REQUESTED,
    SUPPORTED_EVENT_VERSIONS,
    build_envelope,
    deserialize_envelope,
    serialize_envelope,
    validate_event_version,
)
from app.events.errors import MalformedEventPayload, UnknownEventType, UnsupportedEventVersion


def test_build_envelope_assigns_uuid_event_id():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    assert uuid.UUID(event.event_id)  # does not raise


def test_build_envelope_assigns_versioned_schema():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    assert event.event_version == SUPPORTED_EVENT_VERSIONS[EVENT_TYPE_ANALYSIS_REQUESTED] == 1


def test_build_envelope_assigns_iso_timestamp():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    # datetime.fromisoformat round-trips a real ISO 8601 string.
    from datetime import datetime

    datetime.fromisoformat(event.occurred_at)


def test_build_envelope_unknown_event_type_rejected():
    with pytest.raises(UnknownEventType):
        build_envelope(event_type="not.a.real.event", payload={}, correlation_id="c1")


def test_every_supported_event_type_has_an_explicit_version():
    for event_type in (
        EVENT_TYPE_ANALYSIS_REQUESTED,
        EVENT_TYPE_ANALYSIS_COMPLETED,
        EVENT_TYPE_ANALYSIS_FAILED,
    ):
        assert isinstance(SUPPORTED_EVENT_VERSIONS[event_type], int)


def test_serialize_is_deterministic_across_calls():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED,
        payload={"b": 1, "a": 2},
        correlation_id="c1",
        project_id="p1",
        metadata={"partition_key": "1:2"},
    )
    assert serialize_envelope(event) == serialize_envelope(event)


def test_serialize_sorts_keys():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={"z": 1, "a": 2}, correlation_id="c1"
    )
    raw = serialize_envelope(event)
    assert raw.index(b'"a"') < raw.index(b'"z"')
    # top-level envelope keys are also sorted
    assert raw.index(b'"correlation_id"') < raw.index(b'"event_id"')


def test_round_trip_serialize_deserialize():
    original = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED,
        payload={"github_pr_analysis_id": "abc"},
        correlation_id="c1",
        project_id="p1",
        organization_id="o1",
        metadata={"partition_key": "1:2"},
    )
    restored = deserialize_envelope(serialize_envelope(original))
    assert restored == original


def test_deserialize_malformed_json_raises():
    with pytest.raises(MalformedEventPayload):
        deserialize_envelope(b"{not json")


def test_deserialize_non_object_json_raises():
    with pytest.raises(MalformedEventPayload):
        deserialize_envelope(b"[1, 2, 3]")


def test_deserialize_missing_required_field_raises():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    raw = serialize_envelope(event)
    import json

    data = json.loads(raw)
    del data["event_id"]
    with pytest.raises(MalformedEventPayload):
        deserialize_envelope(json.dumps(data).encode())


def test_validate_event_version_accepts_supported_version():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    validate_event_version(event)  # does not raise


def test_validate_event_version_rejects_unsupported_version():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    bumped = dataclasses.replace(event, event_version=999)
    with pytest.raises(UnsupportedEventVersion):
        validate_event_version(bumped)


def test_validate_event_version_rejects_unknown_event_type():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED, payload={}, correlation_id="c1"
    )
    unknown = dataclasses.replace(event, event_type="not.a.real.event")
    with pytest.raises(UnknownEventType):
        validate_event_version(unknown)


def test_metadata_kept_separate_from_payload():
    event = build_envelope(
        event_type=EVENT_TYPE_ANALYSIS_REQUESTED,
        payload={"head_sha": "abc"},
        correlation_id="c1",
        metadata={"partition_key": "1:2"},
    )
    assert "partition_key" not in event.payload
    assert "head_sha" not in event.metadata
