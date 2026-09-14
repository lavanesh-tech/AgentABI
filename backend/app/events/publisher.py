"""`EventPublisher` — the abstraction application services depend on
(Phase 13 spec §8), never `aiokafka` directly. Topic routing is kept out
of the `publish` signature itself (matching the spec's exact Protocol
shape) — each implementation resolves the topic from `event_type` via
`resolve_topic`, and the partition key travels in `event.metadata`
(never a caller-supplied extra argument), keeping transport concerns
attached to the envelope rather than scattered across call sites.
"""

from typing import Protocol

from app.events.envelope import (
    EVENT_TYPE_ANALYSIS_COMPLETED,
    EVENT_TYPE_ANALYSIS_FAILED,
    EVENT_TYPE_ANALYSIS_REQUESTED,
    EventEnvelope,
)
from app.events.errors import UnknownEventType

_REQUEST_EVENT_TYPES = frozenset({EVENT_TYPE_ANALYSIS_REQUESTED})
_RESULT_EVENT_TYPES = frozenset({EVENT_TYPE_ANALYSIS_COMPLETED, EVENT_TYPE_ANALYSIS_FAILED})


def resolve_topic(event_type: str, *, request_topic: str, result_topic: str) -> str:
    """Spec §7's two-topic strategy: one topic for analysis *requests*,
    one for analysis *results* (completed/failed) — not one topic per
    project/organization/PR/event-subtype, which would not scale and
    would make consumer-group partition assignment unmanageable."""

    if event_type in _REQUEST_EVENT_TYPES:
        return request_topic
    if event_type in _RESULT_EVENT_TYPES:
        return result_topic
    raise UnknownEventType(event_type)


class EventPublisher(Protocol):
    async def publish(self, event: EventEnvelope) -> None: ...
