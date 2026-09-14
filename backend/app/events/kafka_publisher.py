"""`KafkaEventPublisher` — the production `EventPublisher` (Phase 13
spec §8/§10). Written and `py_compile`-clean; `aiokafka` is not
installable in this sandbox (same PyPI restriction documented for every
network-dependent module in every prior phase — `httpx`, `openai`,
`neo4j`, `redis` are all in the same position), so this module is not
exercised by `pytest` here. `app/events/fake_publisher.py` is what
`app/kafka/analysis_handler.py` and `GitHubPullRequestAnalysisService`
are actually tested against.
"""

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.events.envelope import EventEnvelope, serialize_envelope
from app.events.errors import TransientEventProcessingError
from app.events.publisher import resolve_topic


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
        try:
            await self._producer.send_and_wait(topic, value=value, key=key)
        except KafkaError as exc:
            # A publish failure is always transient from the caller's
            # perspective (spec §20/§29) — never fabricated as success,
            # never silently swallowed.
            raise TransientEventProcessingError(f"Kafka publish failed: {exc}") from exc


__all__ = ["KafkaEventPublisher"]
