"""Phase 16 spec §6 HTTP metrics tests: normalized route templates (not
raw paths), status-code labeling, duration observation, and unmatched-
route handling without cardinality explosion. Needs `fastapi`/`starlette`/
`httpx` — none installed in this sandbox this session (PyPI unreachable —
see docs/DECISIONS.md). Written and `py_compile`-clean; not pytest-executed.
"""

from app.core.config import Settings
from app.core.metrics_middleware import _route_template
from app.observability import metrics


class _FakeRoute:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRequest:
    def __init__(self, route_path: str | None) -> None:
        self.scope = {"route": _FakeRoute(route_path)} if route_path else {}


def test_route_template_uses_matched_route_path_not_raw_url():
    request = _FakeRequest("/api/v1/projects/{project_id}")
    assert _route_template(request) == "/api/v1/projects/{project_id}"


def test_route_template_falls_back_to_bounded_label_when_unmatched():
    """A 404 for a random probed path must never become an unbounded
    label value — every unmatched route collapses to one fixed string."""

    request = _FakeRequest(None)
    assert _route_template(request) == "unmatched"

    another = _FakeRequest(None)
    assert _route_template(another) == "unmatched"


async def test_middleware_records_request_with_normalized_route_and_status():
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.core.metrics_middleware import PrometheusMetricsMiddleware

    async def handler(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/items/{item_id}", handler)])
    settings = Settings(metrics_enabled=True)
    app.add_middleware(PrometheusMetricsMiddleware, settings=settings)

    calls: list[dict] = []
    original = metrics.record_http_request

    def _spy(settings_arg, **kwargs):
        calls.append(kwargs)
        return original(settings_arg, **kwargs)

    metrics.record_http_request = _spy  # type: ignore[assignment]
    try:
        client = TestClient(app)
        response = client.get("/items/abc-123")
        assert response.status_code == 200
    finally:
        metrics.record_http_request = original  # type: ignore[assignment]

    assert len(calls) == 1
    assert calls[0]["route"] == "/items/{item_id}"
    assert calls[0]["status"] == "200"
    assert calls[0]["method"] == "GET"
    # The raw path parameter value must never leak into the label.
    assert "abc-123" not in calls[0]["route"]
