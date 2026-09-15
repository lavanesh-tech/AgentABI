"""Regression test for the worker healthcheck bug: the `worker` service
in `docker-compose.yml` builds from the same Dockerfile/image as `api`
(same `build:` context, different `command:`), and that image's
Dockerfile bakes in `HEALTHCHECK CMD curl -f http://localhost:8000/api/v1/health`.
Compose only overrides `command:` for `worker`, so without its own
`healthcheck:` override the worker inherited the API's image-level
HEALTHCHECK verbatim — probing a port nothing in the worker process
listens on (it runs the Kafka worker, not uvicorn), so Docker reported
it permanently unhealthy (`curl: (7) Failed to connect to localhost port
8000`) no matter how healthy the actual Kafka consumer was.

Fixed by giving `worker:` its own `healthcheck:` in docker-compose.yml
that probes its real HTTP surface: the Prometheus metrics server on
port 9101 (`start_worker_metrics_server`, started early in
`app.kafka.worker.main()`), which is genuine process liveness —
deliberately not conflated with Kafka connectivity/consumer-group
health, which stays a separate concern.

Pure text/regex inspection of `docker-compose.yml` — no PyYAML import
(not a project dependency), so this actually executes in this sandbox
like this project's other dependency-free regression tests.
"""

from __future__ import annotations

import re
from pathlib import Path

_COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"


def _service_block(compose_text: str, service_name: str) -> str:
    """Returns the raw text of one top-level (2-space-indented) service
    block, from its `  <name>:` line up to (not including) the next
    top-level service key."""

    lines = compose_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^  {re.escape(service_name)}:\s*$", line):
            start = i
            break
    assert start is not None, f"no top-level service {service_name!r} found in docker-compose.yml"

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if re.match(r"^  \S", lines[i]):  # next top-level key (2-space indent, non-space)
            end = i
            break
    return "\n".join(lines[start:end])


def test_worker_has_its_own_healthcheck_override():
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    worker_block = _service_block(compose_text, "worker")

    assert re.search(r"^\s+healthcheck:\s*$", worker_block, re.MULTILINE), (
        "worker service has no healthcheck: override — it will silently inherit "
        "the api image's Dockerfile-level HEALTHCHECK (curl localhost:8000) again"
    )


def test_worker_healthcheck_does_not_probe_the_api_port_or_path():
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    worker_block = _service_block(compose_text, "worker")

    healthcheck_start = worker_block.index("healthcheck:")
    # The healthcheck stanza is the last thing in the worker block in
    # this file; take everything from `healthcheck:` onward.
    healthcheck_text = worker_block[healthcheck_start:]

    assert "8000" not in healthcheck_text, (
        f"worker healthcheck references port 8000 (the API's port) — this is the "
        f"exact regression this test guards against. healthcheck block: {healthcheck_text!r}"
    )
    assert "/api/v1/health" not in healthcheck_text, (
        f"worker healthcheck references the API's health path. "
        f"healthcheck block: {healthcheck_text!r}"
    )


def test_worker_healthcheck_probes_its_own_metrics_port():
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    worker_block = _service_block(compose_text, "worker")

    healthcheck_start = worker_block.index("healthcheck:")
    healthcheck_text = worker_block[healthcheck_start:]

    assert "9101" in healthcheck_text, (
        f"expected the worker healthcheck to probe its own Prometheus metrics "
        f"port (9101) — a real HTTP surface this process actually serves. "
        f"healthcheck block: {healthcheck_text!r}"
    )


def test_api_service_keeps_its_own_dockerfile_healthcheck_unchanged():
    """`api` doesn't declare its own `healthcheck:` in compose — it should
    keep relying on the image's Dockerfile HEALTHCHECK (curl :8000), which
    is correct for `api` and out of scope for this fix. This test exists
    so a future edit that touches `worker`'s healthcheck can't
    accidentally also add/change one for `api` unnoticed."""

    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    api_block = _service_block(compose_text, "api")

    assert "healthcheck:" not in api_block, (
        "api service now has a compose-level healthcheck override — this fix was "
        "scoped to the worker only; api's health behavior must stay on the "
        "Dockerfile's own HEALTHCHECK (curl :8000/api/v1/health)"
    )


def test_dockerfile_healthcheck_still_targets_the_api_port():
    """The image-level HEALTHCHECK itself is unchanged — it's correct for
    `api` (which still runs uvicorn on 8000); only `worker`'s override in
    compose changed."""

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "localhost:8000" in dockerfile
    assert "/api/v1/health" in dockerfile
