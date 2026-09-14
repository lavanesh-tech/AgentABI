"""Kafka worker entrypoint (Phase 13 spec §47): `python -m app.kafka.
worker`. Does not require FastAPI/uvicorn running — it opens its own
short-lived Postgres session per consumed message (mirroring `app.core.
database.get_db_session`'s per-request lifecycle) and drives
`AnalysisRequestHandler`. Written and `py_compile`-clean; not run here —
`aiokafka` is not installable in this sandbox.
"""

import asyncio
import json

import structlog

from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory
from app.core.logging import configure_logging
from app.events.envelope import EventEnvelope, deserialize_envelope
from app.github.checks_client import HttpxGitHubChecksClient, StaticGitHubCredentialProvider
from app.kafka.analysis_handler import AnalysisRequestHandler
from app.kafka.consumer import KafkaEventConsumer
from app.observability import setup_tracing, shutdown_tracing

logger = structlog.get_logger(__name__)


async def _dlq_publish(raw: bytes, failure_category: str, retry_count: int) -> None:
    """Spec §21: the DLQ payload carries the original event id/type/
    version when the bytes at least parse as an envelope, plus the
    failure category, retry count, and correlation id — never a raw
    stack trace or arbitrary error text that could carry sensitive
    detail."""

    settings = get_settings()
    try:
        envelope: EventEnvelope | None = deserialize_envelope(raw)
    except Exception:  # noqa: BLE001 - even unparseable bytes still get a DLQ record
        envelope = None

    dlq_payload = {
        "original_event_id": envelope.event_id if envelope else None,
        "original_event_type": envelope.event_type if envelope else None,
        "original_event_version": envelope.event_version if envelope else None,
        "failure_category": failure_category,
        "retry_count": retry_count,
        "correlation_id": envelope.correlation_id if envelope else None,
    }
    dlq_key = (envelope.event_id if envelope else "unknown").encode("utf-8")

    from app.events.factory import get_event_publisher

    publisher = get_event_publisher(settings)
    await publisher.start()
    # DLQ is a plain topic write, not routed through `resolve_topic`
    # (a DLQ record isn't one of the two domain event types) — send
    # directly via the underlying producer.
    await publisher._producer.send_and_wait(  # noqa: SLF001 - worker-internal, not a public API
        settings.kafka_analysis_dlq_topic,
        value=json.dumps(dlq_payload).encode("utf-8"),
        key=dlq_key,
    )


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    # spec §29: worker telemetry is independent of FastAPI — same
    # resource attributes, different `service.name` so API and worker
    # traces are distinguishable in a backend.
    setup_tracing(settings.model_copy(update={"otel_service_name": "agentabi-worker"}))
    logger.info("kafka_worker_starting", group=settings.kafka_consumer_group)

    session_factory = get_session_factory()
    checks_client = HttpxGitHubChecksClient(
        StaticGitHubCredentialProvider(settings.github_checks_token)
    )

    from app.events.factory import get_event_publisher

    result_publisher = get_event_publisher(settings)
    await result_publisher.start()

    class _SessionScopedHandler:
        """Opens one short-lived session per event (spec §46: a crash
        mid-processing before commit must be safe to redeliver and
        reprocess — never share a long-lived session across events)."""

        async def handle(self, event: EventEnvelope) -> None:
            async with session_factory() as session:
                handler = AnalysisRequestHandler(
                    session, checks_client=checks_client, result_publisher=result_publisher
                )
                try:
                    await handler.handle(event)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

    consumer = KafkaEventConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        client_id=settings.kafka_client_id,
        group_id=settings.kafka_consumer_group,
        topics=[settings.kafka_analysis_request_topic],
        handler=_SessionScopedHandler(),
        dlq_publish=_dlq_publish,
    )
    await consumer.start()
    try:
        await consumer.run_forever()
    finally:
        await consumer.stop()
        await result_publisher.stop()
        await dispose_engine()
        shutdown_tracing()
        logger.info("kafka_worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
