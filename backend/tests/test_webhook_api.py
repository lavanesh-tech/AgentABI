"""GitHub webhook ingestion API — integration tests (Security Phase E
spec §27). Written and `py_compile`-clean; needs SQLAlchemy/FastAPI/
httpx, unavailable in this sandbox — see docs/DECISIONS.md.
"""

from app.core.config import get_settings
from app.github.webhook_signature import compute_signature

_SECRET = "fake-webhook-secret"  # fake value only


def _configure(monkeypatch):
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", _SECRET)
    get_settings.cache_clear()


async def test_valid_signed_payload_is_accepted(client, session, monkeypatch):
    _configure(monkeypatch)
    payload = b'{"zen": "hello"}'
    response = await client.post(
        "/api/v1/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": compute_signature(_SECRET, payload),
            "X-GitHub-Delivery": "api-delivery-1",
            "X-GitHub-Event": "ping",
        },
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert "x-correlation-id" in {k.lower() for k in response.headers}


async def test_invalid_signature_is_rejected(client, session, monkeypatch):
    _configure(monkeypatch)
    payload = b'{"zen": "hello"}'
    response = await client.post(
        "/api/v1/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "X-GitHub-Delivery": "api-delivery-2",
            "X-GitHub-Event": "ping",
        },
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INVALID_WEBHOOK_SIGNATURE"
    assert "request_id" in body["error"]


async def test_missing_signature_is_rejected(client, session, monkeypatch):
    _configure(monkeypatch)
    response = await client.post(
        "/api/v1/github/webhook",
        content=b'{"zen": "hello"}',
        headers={"Content-Type": "application/json", "X-GitHub-Delivery": "api-delivery-3"},
    )
    assert response.status_code == 401


async def test_modified_body_is_rejected(client, session, monkeypatch):
    _configure(monkeypatch)
    payload = b'{"zen": "original"}'
    signature = compute_signature(_SECRET, payload)
    response = await client.post(
        "/api/v1/github/webhook",
        content=payload + b" tampered",
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "api-delivery-4",
            "X-GitHub-Event": "ping",
        },
    )
    assert response.status_code == 401


async def test_missing_delivery_id_after_valid_signature_is_validation_error(
    client, session, monkeypatch
):
    _configure(monkeypatch)
    payload = b'{"zen": "no-id"}'
    response = await client.post(
        "/api/v1/github/webhook",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": compute_signature(_SECRET, payload),
            "X-GitHub-Event": "ping",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


async def test_valid_duplicate_delivery_is_idempotent(client, session, monkeypatch):
    _configure(monkeypatch)
    payload = b'{"zen": "dup"}'
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": compute_signature(_SECRET, payload),
        "X-GitHub-Delivery": "api-delivery-5",
        "X-GitHub-Event": "ping",
    }
    first = await client.post("/api/v1/github/webhook", content=payload, headers=headers)
    second = await client.post("/api/v1/github/webhook", content=payload, headers=headers)
    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate"


async def test_conflicting_duplicate_delivery_returns_409(client, session, monkeypatch):
    _configure(monkeypatch)
    delivery_id = "api-delivery-6"
    payload_a = b'{"zen": "a"}'
    payload_b = b'{"zen": "b"}'
    await client.post(
        "/api/v1/github/webhook",
        content=payload_a,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": compute_signature(_SECRET, payload_a),
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "ping",
        },
    )
    response = await client.post(
        "/api/v1/github/webhook",
        content=payload_b,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": compute_signature(_SECRET, payload_b),
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": "ping",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_rate_limiting_still_applies(client, session, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_MUTATION_REQUESTS", "2")
    monkeypatch.setenv("RATE_LIMIT_MUTATION_WINDOW_SECONDS", "60")
    _configure(monkeypatch)

    statuses = []
    for i in range(4):
        payload = f'{{"zen": "{i}"}}'.encode()
        response = await client.post(
            "/api/v1/github/webhook",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": compute_signature(_SECRET, payload),
                "X-GitHub-Delivery": f"rate-delivery-{i}",
                "X-GitHub-Event": "ping",
            },
        )
        statuses.append(response.status_code)
    assert 429 in statuses
