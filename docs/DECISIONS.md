# Architecture Decision Log

Short-form ADRs. Newest first.

## ADR-001 — Kafka in KRaft mode, no Zookeeper (2026-09-13)

**Decision:** Use `bitnami/kafka` in KRaft (combined broker+controller) mode
in `docker-compose.yml`.

**Why:** Zookeeper is legacy for new Kafka deployments (deprecated as of
Kafka 3.x/4.0 direction); KRaft is simpler to run locally (one container
instead of two) and matches what a new deployment would use in 2026.

**Alternative considered:** `confluentinc/cp-kafka` + Zookeeper — more
"enterprise-familiar" but adds an extra container and legacy surface area
with no benefit for a portfolio project.

## ADR-002 — asyncpg driver + SQLAlchemy 2.0 async (2026-09-13)

**Decision:** `postgres_dsn` defaults to `postgresql+asyncpg://...`; the app
is async end-to-end (FastAPI async routes, SQLAlchemy 2.0 async engine in
Phase 2, async Neo4j driver in Phase 4).

**Why:** The pipeline (webhook → diff → graph traversal → replay → risk
scoring) is I/O-bound across Postgres, Neo4j, Redis, Kafka, and two LLM
providers — async lets those overlap instead of serializing on threads.

**Alternative considered:** Sync SQLAlchemy + threadpool (simpler mental
model, but fights FastAPI's async-native design and complicates the
eventual Kafka consumer workers).

## ADR-003 — structlog for structured logging (2026-09-13)

**Decision:** structlog configured to emit console-renderer logs locally,
JSON in staging/production, with correlation IDs threaded via contextvars.

**Why:** Native Python `logging` + manual JSON formatting works but structlog
gives contextvar-based request binding (needed for correlation IDs across
async code) and processor pipelines for free.

**Alternative considered:** stdlib `logging` + `python-json-logger` only —
kept as a dependency for the formatter but structlog owns the pipeline.

## ADR-004 — Settings via pydantic-settings, one Settings class (2026-09-13)

**Decision:** All configuration lives in `app/core/config.py::Settings`,
loaded from environment/`.env`, cached via `lru_cache`-wrapped
`get_settings()`.

**Why:** Single source of truth, type-validated at startup (fails fast on
bad config), easy to override in tests.

## ADR-005 — Phase 1 network/Docker verification gap (2026-09-13)

**Context:** This development sandbox has no reachable PyPI (outbound egress
policy returns `403 host_not_allowed` for `pypi.org`/`files.pythonhosted.org`)
and no running Docker daemon. This is an environment restriction, not a
project decision.

**Impact:** Phase 1 could not run `pip install`, `pytest`, `mypy` against the
real dependency set, or `docker build` / `docker compose up` inside this
session. What *was* verified: `ruff format --check` / `ruff check` (clean),
`python -m py_compile` on every backend file (clean), and
`docker compose config` (schema-valid).

**Action for the user:** run `make install && make lint && make typecheck &&
make test` and `make infra-up` locally (or in an environment with normal
network/Docker access) before treating Phase 1 as fully proven. Documented
here rather than silently claimed as done, per the project's "no fake
functionality" rule.
