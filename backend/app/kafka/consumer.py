"""`KafkaEventConsumer` — the transport-specific loop (Phase 13 spec §9/
§19/§20/§21/§22/§26). Owns deserialize -> validate -> dispatch -> commit;
domain execution lives entirely in the injected `EventHandler` (`app/
kafka/analysis_handler.py`). Written and `py_compile`-clean; `aiokafka`
is not installable in this sandbox (same restriction as every other
network-dependent module — see `app/events/kafka_publisher.py`), so this
module is not exercised by `pytest` here.
"""

from collections.abc import Awaitable, Callable

import structlog
from aiokafka import AIOKafkaConsumer

from app.events.envelope import EventEnvelope, deserialize_envelope
from app.events.errors import (
    MalformedEventPayload,
    PermanentEventProcessingError,
    TransientEventProcessingError,
    UnsupportedEventVersion,
)
from app.events.handler import EventHandler

logger = structlog.get_logger(__name__)

# Bounded retry (spec §20) — not a busy-loop, not unbounded. Exceeding
# this routes the message to the dead-letter topic (spec §21) rather
# than retrying forever.
_MAX_TRANSIENT_RETRIES = 3

DlqPublish = Callable[[bytes, str, int], Awaitable[None]]
"""`(raw_message_bytes, failure_category, retry_count) -> None` — kept as
a plain callable rather than another `EventPublisher.publish()` call
since a DLQ message isn't a domain event; it's the original bytes plus
failure metadata, which may not even be a valid `EventEnvelope`."""


class KafkaEventConsumer:
    """One-message-at-a-time processing (spec §26: no unlimited
    concurrent tasks) — `aiokafka`'s default async-iterator consumption
    is naturally bounded this way; this class never spawns a task per
    message."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        group_id: str,
        topics: list[str],
        handler: EventHandler,
        dlq_publish: DlqPublish | None = None,
    ) -> None:
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            group_id=group_id,
            enable_auto_commit=False,  # spec §19: commit only after safe processing
        )
        self._handler = handler
        self._dlq_publish = dlq_publish

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def run_forever(self) -> None:
        async for message in self._consumer:
            await self._process_one(message)

    async def _process_one(self, message) -> None:  # noqa: ANN001 - aiokafka ConsumerRecord
        try:
            envelope = deserialize_envelope(message.value)
        except MalformedEventPayload:
            # Poison message (spec §22): logged with safe metadata only,
            # routed to DLQ if configured, and the loop continues — never
            # a raw exception body or the message bytes themselves.
            logger.warning(
                "kafka_poison_message",
                topic=message.topic,
                partition=message.partition,
                offset=message.offset,
            )
            await self._to_dlq(message, "malformed_payload", retry_count=0)
            await self._consumer.commit()
            return

        await self._dispatch_with_retry(message, envelope)

    async def _dispatch_with_retry(self, message, envelope: EventEnvelope) -> None:  # noqa: ANN001
        attempt = 0
        while True:
            try:
                await self._handler.handle(envelope)
                await self._consumer.commit()
                logger.info(
                    "kafka_event_processed",
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                    topic=message.topic,
                    partition=message.partition,
                    offset=message.offset,
                    correlation_id=envelope.correlation_id,
                    retry_count=attempt,
                )
                return
            except UnsupportedEventVersion:
                # Spec §6: fail safely, never reinterpret — permanent.
                logger.warning(
                    "kafka_unsupported_event_version",
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                )
                await self._to_dlq(message, "unsupported_event_version", retry_count=attempt)
                await self._consumer.commit()
                return
            except PermanentEventProcessingError:
                logger.warning(
                    "kafka_permanent_processing_failure",
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                    retry_count=attempt,
                )
                await self._to_dlq(message, "permanent_processing_error", retry_count=attempt)
                await self._consumer.commit()
                return
            except TransientEventProcessingError:
                attempt += 1
                if attempt > _MAX_TRANSIENT_RETRIES:
                    logger.warning(
                        "kafka_transient_retries_exhausted",
                        event_id=envelope.event_id,
                        event_type=envelope.event_type,
                        retry_count=attempt,
                    )
                    await self._to_dlq(message, "transient_retries_exhausted", retry_count=attempt)
                    await self._consumer.commit()
                    return
                logger.info(
                    "kafka_transient_retry",
                    event_id=envelope.event_id,
                    event_type=envelope.event_type,
                    retry_count=attempt,
                )
                # No commit — a crash here means Kafka redelivers this
                # message, and the handler is required to be idempotent
                # (spec §17/§46) so that's safe, not a duplicate-effect
                # risk.

    async def _to_dlq(self, message, failure_category: str, *, retry_count: int) -> None:  # noqa: ANN001
        if self._dlq_publish is None:
            return
        try:
            await self._dlq_publish(message.value, failure_category, retry_count)
        except Exception:  # noqa: BLE001 - the consumer loop must never crash on a DLQ failure
            logger.exception("kafka_dlq_publish_failed", topic=message.topic)


__all__ = ["KafkaEventConsumer"]
