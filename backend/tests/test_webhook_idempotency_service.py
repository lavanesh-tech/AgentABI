"""GitHubWebhookService idempotency — integration tests (Security Phase
E spec §25). Written and `py_compile`-clean; needs SQLAlchemy, unavailable
in this sandbox — see docs/DECISIONS.md. Uses the real `session` fixture
(`tests/conftest.py`) against a real Postgres test database.
"""

from app.core.config import get_settings
from app.domain.exceptions import WebhookDeliveryConflict
from app.github.webhook_signature import compute_signature
from app.services.webhook_service import GitHubWebhookService

_SECRET = "fake-webhook-secret"  # fake value only


def _service(session, monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", _SECRET)
    get_settings.cache_clear()
    return GitHubWebhookService(session, settings=get_settings())


async def test_first_delivery_is_accepted(session, monkeypatch):
    service = _service(session, monkeypatch)
    payload = b'{"zen": "first"}'
    result = await service.process(
        raw_body=payload,
        signature_header=compute_signature(_SECRET, payload),
        delivery_id="delivery-1",
        event_type="ping",
        request_id="req-1",
    )
    assert result.status == "accepted"


async def test_same_id_same_payload_is_idempotent(session, monkeypatch):
    service = _service(session, monkeypatch)
    payload = b'{"zen": "retry"}'
    header = compute_signature(_SECRET, payload)
    first = await service.process(
        raw_body=payload,
        signature_header=header,
        delivery_id="delivery-2",
        event_type="ping",
        request_id="req-2a",
    )
    second = await service.process(
        raw_body=payload,
        signature_header=header,
        delivery_id="delivery-2",
        event_type="ping",
        request_id="req-2b",
    )
    assert first.status == "accepted"
    assert second.status == "duplicate"


async def test_same_id_different_payload_is_conflict(session, monkeypatch):
    service = _service(session, monkeypatch)
    payload_a = b'{"zen": "a"}'
    payload_b = b'{"zen": "b"}'
    await service.process(
        raw_body=payload_a,
        signature_header=compute_signature(_SECRET, payload_a),
        delivery_id="delivery-3",
        event_type="ping",
        request_id="req-3a",
    )
    try:
        await service.process(
            raw_body=payload_b,
            signature_header=compute_signature(_SECRET, payload_b),
            delivery_id="delivery-3",
            event_type="ping",
            request_id="req-3b",
        )
        raise AssertionError("expected WebhookDeliveryConflict")
    except WebhookDeliveryConflict as exc:
        assert exc.delivery_id == "delivery-3"


async def test_different_delivery_ids_are_independent(session, monkeypatch):
    service = _service(session, monkeypatch)
    payload = b'{"zen": "independent"}'
    header = compute_signature(_SECRET, payload)
    first = await service.process(
        raw_body=payload,
        signature_header=header,
        delivery_id="delivery-4a",
        event_type="ping",
        request_id="req-4a",
    )
    second = await service.process(
        raw_body=payload,
        signature_header=header,
        delivery_id="delivery-4b",
        event_type="ping",
        request_id="req-4b",
    )
    assert first.status == "accepted"
    assert second.status == "accepted"
