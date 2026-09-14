"""Process-wide `EventPublisher` singleton (mirrors `app/core/database.
py`'s `get_engine()`/`dispose_engine()` pattern). Created lazily on
first publish, not eagerly at app startup — so a local/unit-test process
with `KAFKA_ENABLED=false` never even imports `aiokafka` at startup
(spec §12: Kafka must not make app startup fail unnecessarily). Only
called from `app/api/v1/github_webhook.py` when `settings.kafka_enabled`
is true.
"""

from app.core.config import Settings, get_settings
from app.events.kafka_publisher import KafkaEventPublisher

_publisher: KafkaEventPublisher | None = None


def get_event_publisher(settings: Settings | None = None) -> KafkaEventPublisher:
    global _publisher
    if _publisher is None:
        settings = settings or get_settings()
        _publisher = KafkaEventPublisher(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=settings.kafka_client_id,
            request_topic=settings.kafka_analysis_request_topic,
            result_topic=settings.kafka_analysis_result_topic,
        )
    return _publisher


async def dispose_event_publisher() -> None:
    global _publisher
    if _publisher is not None:
        await _publisher.stop()
    _publisher = None


__all__ = ["dispose_event_publisher", "get_event_publisher"]
