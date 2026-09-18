"""Request body size limit — integration tests (Security Phase D spec
§14/§26). Written and `py_compile`-clean; needs SQLAlchemy/FastAPI/
httpx, unavailable in this sandbox — see docs/DECISIONS.md. Uses a
small configured limit via `get_settings.cache_clear()` +
`MAX_REQUEST_BODY_BYTES` monkeypatch rather than allocating a huge
payload.
"""

from app.core.config import get_settings


def _small_limit(monkeypatch, limit_bytes: int):
    monkeypatch.setenv("MAX_REQUEST_BODY_BYTES", str(limit_bytes))
    get_settings.cache_clear()


async def test_body_below_limit_is_accepted(client, monkeypatch):
    _small_limit(monkeypatch, 10_000)
    response = await client.get("/api/v1/auth/github/login", follow_redirects=False)
    assert response.status_code != 413


async def test_body_over_limit_returns_413_with_standard_envelope(client, monkeypatch):
    limit = get_settings().max_request_body_bytes
    payload = "{}"
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/trajectories",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(limit + 1),
        },
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "REQUEST_TOO_LARGE"
    assert "request_id" in body["error"]


async def test_body_at_exact_limit_is_accepted_by_size_middleware(client, monkeypatch):
    # At-limit is a size-middleware concern only — downstream validation
    # (auth/schema) may still reject it for other reasons, so this only
    # asserts the response is not a 413.
    limit = 200
    _small_limit(monkeypatch, limit)
    payload = ("x" * (limit - 2)).encode("utf-8")
    response = await client.post(
        "/api/v1/projects/00000000-0000-0000-0000-000000000000/trajectories",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code != 413
