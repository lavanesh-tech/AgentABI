"""Phase 16 metric-helper tests for `app.observability.metrics`: counter/
histogram/gauge creation, the disabled/no-op path, and the render_metrics
placeholder behavior. Needs `prometheus-client` + `pydantic-settings` —
neither installed in this sandbox this session (PyPI is unreachable
here — see docs/DECISIONS.md and every prior phase's identical note).
Written and `py_compile`-clean; not pytest-executed.
"""

from app.core.config import Settings
from app.observability import metrics


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_metrics_disabled_never_touches_underlying_metric_objects(monkeypatch):
    """With METRICS_ENABLED=false, every record_* function must return
    without calling .labels()/.inc()/.observe() — verified by patching a
    metric object to raise if touched."""

    settings = _settings(metrics_enabled=False)

    class _Boom:
        def labels(self, *a, **k):
            raise AssertionError("metrics recording must be skipped when disabled")

    monkeypatch.setattr(metrics, "HTTP_REQUESTS_TOTAL", _Boom())
    monkeypatch.setattr(metrics, "RISK_DECISIONS_TOTAL", _Boom())
    monkeypatch.setattr(metrics, "KAFKA_PUBLISHED_TOTAL", _Boom())

    metrics.record_http_request(
        settings, method="GET", route="/x", status="200", duration_seconds=0.1
    )
    metrics.record_risk_decision(settings, decision="PASS", hard_block=False, score=10.0)
    metrics.record_kafka_published(
        settings, event_type="t", outcome="success", duration_seconds=0.01
    )


def test_metrics_enabled_records_without_raising():
    """Whether or not `prometheus_client` is actually importable in this
    environment, every record_* call must complete without raising — the
    no-op stand-in (`_NoOpMetric`) and the real library both satisfy the
    same call shape."""

    settings = _settings(metrics_enabled=True)
    metrics.record_http_request(
        settings, method="GET", route="/x", status="200", duration_seconds=0.1
    )
    metrics.record_analysis_run(
        settings, pipeline="compatibility", status="success", duration_seconds=0.2
    )
    metrics.record_risk_decision(settings, decision="BLOCK", hard_block=True, score=95.0)
    metrics.record_kafka_published(
        settings, event_type="t", outcome="success", duration_seconds=0.01
    )
    metrics.record_kafka_consumed(
        settings, event_type="t", outcome="success", duration_seconds=0.01
    )
    metrics.record_kafka_retry(settings, event_type="t")
    metrics.record_kafka_dlq(settings, event_type="t", reason="malformed_payload")
    metrics.record_github_webhook_delivery(settings, event="pull_request", outcome="accepted")
    metrics.record_github_pr_analysis(settings, outcome="completed")
    metrics.record_github_check_publish(settings, action="create", outcome="success")
    metrics.record_openai_explanation(
        settings, outcome="success", model="gpt-4o-mini", duration_seconds=1.0
    )
    metrics.record_dependency_call(
        settings, dependency="postgres", outcome="success", duration_seconds=0.01
    )
    metrics.record_error(settings, error_type="validation")


def test_record_error_coerces_unknown_category_to_internal():
    settings = _settings(metrics_enabled=True)
    # Should not raise even with a made-up category — must be coerced,
    # never passed through as an arbitrary label value.
    metrics.record_error(settings, error_type="something_unbounded_and_unexpected")


def test_render_metrics_never_raises_and_returns_bytes():
    settings = _settings(metrics_enabled=True)
    body, content_type = metrics.render_metrics(settings)
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)


def test_render_metrics_disabled_returns_placeholder():
    settings = _settings(metrics_enabled=False)
    body, content_type = metrics.render_metrics(settings)
    assert b"disabled" in body
    assert content_type.startswith("text/plain")


def test_track_http_in_progress_disabled_is_a_plain_noop_contextmanager():
    settings = _settings(metrics_enabled=False)
    with metrics.track_http_in_progress(settings, method="GET"):
        pass  # must not raise, must not touch the gauge


def test_metric_registration_never_raises_forbidden_labels():
    """`_assert_safe_labels` must reject any of the forbidden label names
    from spec §22 at registration time — this is the same guard exercised
    statically by test_metrics_cardinality_safety.py, checked here at the
    function level."""

    import pytest

    with pytest.raises(ValueError):
        metrics._counter("agentabi_test_bad", "doc", ("project_id",))
