"""`EventHandler` — the consumer-side dispatch boundary (Phase 13 spec
§9). Transport-specific Kafka code (`app/kafka/consumer.py`) owns
deserialize/validate/dispatch/commit; domain execution lives entirely in
a handler implementation (`app/kafka/analysis_handler.py`), never in the
consumer loop itself.
"""

from typing import Protocol

from app.events.envelope import EventEnvelope


class EventHandler(Protocol):
    async def handle(self, event: EventEnvelope) -> None: ...
