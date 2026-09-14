"""Consumer-side processing outcomes (Phase 13 spec §20/§22). Distinct
from `app.domain.exceptions` (HTTP-facing domain errors): these classify
*how a Kafka message should be handled* — retried, dead-lettered, or
committed as a permanent failure — never how an API response is shaped.
Pure stdlib — no aiokafka/SQLAlchemy import.
"""


class EventProcessingError(Exception):
    """Base class for every consumer-side event handling failure."""


class TransientEventProcessingError(EventProcessingError):
    """A failure that may succeed on retry (e.g. a transient Postgres or
    GitHub API blip) — spec §20's bounded-retry-worthy category."""


class PermanentEventProcessingError(EventProcessingError):
    """A failure that will never succeed no matter how many times it is
    retried (malformed payload, unsupported schema version, a permanent
    validation/config error) — spec §20/§21: never retried, routed to
    the dead-letter topic (or logged and committed) instead."""


class MalformedEventPayload(PermanentEventProcessingError):
    """Raised for invalid JSON or a payload missing/mistyping a required
    field (spec §22's "poison message" case) — the consumer loop must
    keep running, never crash, on this."""


class UnknownEventType(PermanentEventProcessingError):
    def __init__(self, event_type: str) -> None:
        super().__init__(f"unknown event_type {event_type!r}")
        self.event_type = event_type


class UnsupportedEventVersion(PermanentEventProcessingError):
    """Spec §6: consumers must validate the schema version and fail
    safely on an unsupported one — never silently reinterpret an
    incompatible payload."""

    def __init__(self, event_type: str, got_version: int, expected_version: int) -> None:
        super().__init__(
            f"unsupported event_version {got_version} for {event_type!r} "
            f"(expected {expected_version})"
        )
        self.event_type = event_type
        self.got_version = got_version
        self.expected_version = expected_version
