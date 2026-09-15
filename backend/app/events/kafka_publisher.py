"""`KafkaEventPublisher` — the production `EventPublisher` (Phase 13
spec §8/§10). Written and `py_compile`-clean; `aiokafka` is not
installable in this sandbox (same PyPI restriction documented for every
network-dependent module in every prior phase — `httpx`, `openai`,
`neo4j`, `redis` are all in the same position), so this module is not
exercised by `pytest` here. `app/events/fake_publisher.py` is what
`app/kafka/analysis_handler.py` and `GitHubPullRequestAnalysisService`
are actually tested against.
"""

import time

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.config import get_settings
from app.events.envelope import EventEnvelope, serialize_envelope
from app.events.errors import TransientEventProcessingError
from app.events.publisher import resolve_topic
from app.observability import inject_trace_headers, record_kafka_published, start_span


class KafkaEventPublisher:
    """Thin wrapper over `aiokafka.AIOKafkaProducer` — never touched by
    application/service code directly (spec §8: services depend on the
    `EventPublisher` Protocol only)."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        request_topic: str,
        result_topic: str,
    ) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers, client_id=client_id)
        self._request_topic = request_topic
        self._result_topic = result_topic
        self._started = False

    async def start(self) -> None:
        if not self._started:
            await self._producer.start()
            self._started = True

    async def stop(self) -> None:
        if self._started:
            await self._producer.stop()
            self._started = False

    async def publish(self, event: EventEnvelope) -> None:
        await self.start()
        topic = resolve_topic(
            event.event_type,
            request_topic=self._request_topic,
            result_topic=self._result_topic,
        )
        key = event.metadata.get("partition_key", event.event_id).encode("utf-8")
        value = serialize_envelope(event)
        # spec §10 (mandatory): W3C trace context travels in Kafka
        # message headers, never inside the event payload — the
        # envelope/schema is byte-for-byte unchanged by tracing.
        headers = inject_trace_headers()
        with start_span(
            "agentabi.kafka.publish",
            kind="producer",
            attributes={
                "messaging.system": "kafka",
                "messaging.destination": topic,
                "agentabi.event_id": event.event_id,
                "agentabi.event_type": event.event_type,
                "agentabi.correlation_id": event.correlation_id,
            },
        ):
            publish_start = time.monotonic()
            try:
                await self._producer.send_and_wait(topic, value=value, key=key, headers=headers)
            except KafkaError as exc:
                record_kafka_published(
                    get_settings(),
                    event_type=event.event_type,
                    outcome="failure",
                    duration_seconds=time.monotonic() - publish_start,
                )
                # A publish failure is always transient from the caller's
                # perspective (spec §20/§29) — never fabricated as success,
                # never silently swallowed.
                raise TransientEventProcessingError(f"Kafka publish failed: {exc}") from exc
            record_kafka_published(
                get_settings(),
                event_type=event.event_type,
                outcome="success",
                duration_seconds=time.monotonic() - publish_start,
            )


__all__ = ["KafkaEventPublisher"]
