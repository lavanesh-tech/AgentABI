"""`EventEnvelope` — the one typed, versioned shape every Kafka message
this integration ever produces or consumes uses (Phase 13 spec §5/§6).
Transport metadata (`metadata`, e.g. the partition key or a DLQ retry
count) is kept structurally separate from the domain `payload` dict, so
a consumer can reason about delivery mechanics without ever needing to
parse the payload, and vice versa. Pure stdlib only, deliberately
`json` rather than the `orjson` dependency already declared in
`pyproject.toml`: `orjson` is not installable in this sandbox (same
PyPI restriction as every other compiled dependency), and this module
is exactly the one Phase 13 needs to stay `pytest --noconftest`-
executable for its mandatory pure event-schema tests (spec §35) — no
SQLAlchemy/FastAPI/aiokafka import either.
"""

import dataclasses
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.events.errors import MalformedEventPayload, UnknownEventType, UnsupportedEventVersion

EVENT_TYPE_ANALYSIS_REQUESTED = "github.pr.analysis.requested"
EVENT_TYPE_ANALYSIS_COMPLETED = "github.pr.analysis.completed"
EVENT_TYPE_ANALYSIS_FAILED = "github.pr.analysis.failed"

# Explicit schema version per event type (spec §6) — bump the value here,
# never reuse a version number for an incompatible payload shape.
SUPPORTED_EVENT_VERSIONS: dict[str, int] = {
    EVENT_TYPE_ANALYSIS_REQUESTED: 1,
    EVENT_TYPE_ANALYSIS_COMPLETED: 1,
    EVENT_TYPE_ANALYSIS_FAILED: 1,
}


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    event_type: str
    event_version: int
    occurred_at: str
    correlation_id: str
    project_id: str | None
    organization_id: str | None
    payload: dict[str, Any]
    metadata: dict[str, str] = field(default_factory=dict)


def build_envelope(
    *,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str,
    project_id: str | None = None,
    organization_id: str | None = None,
    metadata: dict[str, str] | None = None,
) -> EventEnvelope:
    """The only place an `EventEnvelope` is constructed for production
    use — `event_id`/`occurred_at`/`event_version` are always derived
    here, never passed in by a caller (spec §5: UUID id, ISO timestamp,
    versioned schema)."""

    if event_type not in SUPPORTED_EVENT_VERSIONS:
        raise UnknownEventType(event_type)

    return EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type=event_type,
        event_version=SUPPORTED_EVENT_VERSIONS[event_type],
        occurred_at=datetime.now(UTC).isoformat(),
        correlation_id=correlation_id,
        project_id=project_id,
        organization_id=organization_id,
        payload=payload,
        metadata=metadata or {},
    )


def serialize_envelope(envelope: EventEnvelope) -> bytes:
    """Deterministic JSON (spec §5/§23): `sort_keys=True`, no Python
    object pickling — two calls with the same envelope content always
    produce byte-identical output."""

    return json.dumps(dataclasses.asdict(envelope), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def deserialize_envelope(raw: bytes) -> EventEnvelope:
    """Raises `MalformedEventPayload` for invalid JSON or a missing/
    mistyped required field (spec §22's poison-message case) — never an
    unhandled `KeyError`/`TypeError` that could crash a consumer loop."""

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedEventPayload(f"event body is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise MalformedEventPayload("event body is not a JSON object")

    try:
        return EventEnvelope(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            event_version=int(data["event_version"]),
            occurred_at=str(data["occurred_at"]),
            correlation_id=str(data["correlation_id"]),
            project_id=(str(data["project_id"]) if data.get("project_id") is not None else None),
            organization_id=(
                str(data["organization_id"]) if data.get("organization_id") is not None else None
            ),
            payload=dict(data["payload"]),
            metadata={str(k): str(v) for k, v in dict(data.get("metadata") or {}).items()},
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise MalformedEventPayload(f"event envelope missing/malformed field: {exc}") from exc


def validate_event_version(envelope: EventEnvelope) -> None:
    """Spec §6: consumers must validate the schema version and fail
    safely (never silently reinterpret) on an unsupported one."""

    expected = SUPPORTED_EVENT_VERSIONS.get(envelope.event_type)
    if expected is None:
        raise UnknownEventType(envelope.event_type)
    if envelope.event_version != expected:
        raise UnsupportedEventVersion(envelope.event_type, envelope.event_version, expected)


__all__ = [
    "EVENT_TYPE_ANALYSIS_COMPLETED",
    "EVENT_TYPE_ANALYSIS_FAILED",
    "EVENT_TYPE_ANALYSIS_REQUESTED",
    "SUPPORTED_EVENT_VERSIONS",
    "EventEnvelope",
    "build_envelope",
    "deserialize_envelope",
    "serialize_envelope",
    "validate_event_version",
]
