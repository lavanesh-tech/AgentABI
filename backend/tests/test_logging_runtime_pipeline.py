"""Regression test for the structlog runtime crash: `logger_factory=
structlog.PrintLoggerFactory()` handed a `PrintLogger` (no `.name`
attribute) to the `structlog.stdlib.add_logger_name` processor, which
unconditionally reads `logger.name` — every real log call (API startup,
worker metrics-server startup) raised `AttributeError: 'PrintLogger'
object has no attribute 'name'` and crashed both processes.

Unlike `test_observability_log_correlation.py`'s pure-function tests,
these exercise actual `logger.info()`/`logger.warning()`/`logger.
exception()` calls through the real configured pipeline (`configure_
logging` + `get_logger`), which is exactly the call shape that crashed
at runtime — a processor-only or AST-only test would not have caught
this, since the bug only surfaces when a message is actually emitted
through the configured `logger_factory`/`wrapper_class` pair.

Needs `structlog`/`pydantic` (`app.core.config.Settings`) installed, so
— like every other test in this project that imports those — it is not
pytest-executable in this sandbox this session (PyPI unreachable, see
docs/DECISIONS.md); it runs for real once dependencies are installed
(this project's Docker image, or a local venv).
"""

from __future__ import annotations

import json
import logging

import pytest
import structlog

from app.core.config import Settings
from app.core.logging import configure_logging, get_logger


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """`logging.basicConfig()` is a no-op if the root logger already has
    handlers, so without this, only the first test in this module would
    actually reconfigure stdout capture — later tests would silently
    write to a stale stream and appear to pass without checking anything.
    """

    logging.root.handlers.clear()
    yield
    logging.root.handlers.clear()


def _configure(log_format: str) -> None:
    settings = Settings(log_level="INFO", log_format=log_format)
    configure_logging(settings)


def test_json_pipeline_logs_do_not_raise_and_are_well_formed(capsys):
    _configure("json")
    logger = get_logger(__name__)

    # This exact call shape (module-level logger, plain .info()) is what
    # crashed API startup in app.main's lifespan handler.
    logger.info("startup_test", environment="test")
    # And .warning() is what crashed inside start_worker_metrics_server's
    # own except-block, terminating the worker a second time.
    logger.warning("warning_test")

    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 2, "expected exactly one JSON line per log call"

    first = json.loads(lines[0])
    assert first["event"] == "startup_test"
    assert first["environment"] == "test"
    assert first["level"] == "info"
    assert first["logger"] == __name__  # add_logger_name must not crash

    second = json.loads(lines[1])
    assert second["event"] == "warning_test"
    assert second["level"] == "warning"


def test_console_pipeline_logs_do_not_raise(capsys):
    _configure("console")
    logger = get_logger(__name__)

    logger.info("startup_test", environment="test")
    logger.warning("warning_test")

    out = capsys.readouterr().out
    assert "startup_test" in out
    assert "warning_test" in out


def test_exception_logging_does_not_raise(capsys):
    _configure("json")
    logger = get_logger(__name__)

    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("handled_error")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["event"] == "handled_error"
    assert "ValueError" in payload.get("exception", "")


def test_worker_metrics_startup_log_calls_do_not_raise(capsys):
    """Reproduces the worker's exact crash path — `start_worker_metrics_
    server`'s `logger.info("metrics_worker_server_started", ...)` on
    success and `logger.warning("metrics_worker_server_failed", ...)` on
    failure — without binding a real port, since only the logging calls
    themselves (not `prometheus_client.start_http_server`) are what
    raised."""

    _configure("json")
    logger = get_logger("app.observability.metrics")

    logger.info("metrics_worker_server_started", port=9101)
    logger.warning("metrics_worker_server_failed", error="simulated for this test")

    lines = [line for line in capsys.readouterr().out.strip().splitlines() if line]
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "metrics_worker_server_started"
    assert json.loads(lines[1])["event"] == "metrics_worker_server_failed"


def test_get_logger_returns_a_real_stdlib_bound_logger():
    """`get_logger`'s own return-type annotation is `structlog.stdlib.
    BoundLogger` — assert the runtime type actually matches it, since
    before this fix it silently didn't (the configured wrapper_class was
    `make_filtering_bound_logger`, a different, generic class)."""

    _configure("json")
    logger = get_logger(__name__)
    assert isinstance(logger, structlog.stdlib.BoundLogger)
