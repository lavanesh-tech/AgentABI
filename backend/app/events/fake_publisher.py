"""`InMemoryEventPublisher` — the `EventPublisher` test double (Phase 13
spec §8/§34/§36: "no Kafka process required for pure tests"). Lives in
the production tree (not test-local) since more than one test module
needs it, mirroring `app.github.checks_fake.FakeGitHubChecksClient`'s
reason for existing there.
"""

from dataclasses import dataclass, field

from app.events.envelope import EventEnvelope, serialize_envelope
from app.events.publisher import resolve_topic


@dataclass(frozen=True, slots=True)
class PublishedEvent:
    """One recorded `publish()` call — topic, partition key, the event
    itself, and its exact serialized bytes, so a test can assert on
    whatever it needs (spec §34)."""

    topic: str
    key: str
    event: EventEnvelope
    serialized: bytes


@dataclass
class InMemoryEventPublisher:
    request_topic: str = "agentabi.analysis.requests"
    result_topic: str = "agentabi.analysis.results"
    published: list[PublishedEvent] = field(default_factory=list)
    fail_with: Exception | None = None

    async def publish(self, event: EventEnvelope) -> None:
        if self.fail_with is not None:
            exc, self.fail_with = self.fail_with, None
            raise exc

        topic = resolve_topic(
            event.event_type, request_topic=self.request_topic, result_topic=self.result_topic
        )
        key = event.metadata.get("partition_key", event.event_id)
        self.published.append(
            PublishedEvent(topic=topic, key=key, event=event, serialized=serialize_envelope(event))
        )


__all__ = ["InMemoryEventPublisher", "PublishedEvent"]
