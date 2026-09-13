# Architecture Decision Log

Short-form ADRs. Newest first.

## ADR-008 — Verify migrations by direct DDL execution, not `alembic upgrade` (2026-09-13)

**Context:** Same sandbox network restriction as ADR-005/ADR-006 — the
`alembic` package itself cannot be installed here, so `alembic upgrade
head` cannot be run in this session.

**Decision:** Hand-transcribed the initial migration's `upgrade()` into raw
SQL and ran it directly against a real local Postgres 16 (`agentabi_test`),
then exercised every constraint by hand (duplicate slug, duplicate
`(organization_id, slug)`, duplicate membership, cascade delete on
organization removal) before dropping the schema again. This proves the
DDL and constraints are correct Postgres, even though the Alembic tool
itself wasn't exercised.

**Why not skip verification entirely:** The project's rule against fake
functionality — "prove what can reasonably be proven" — is more strongly
served by real-but-partial DB verification than by no DB verification at
all.

**Residual risk:** A typo that makes the *hand-transcribed* SQL diverge
from what `op.create_table(...)` would actually emit would not be caught
by this method. Running `alembic upgrade head` for real (see ROADMAP.md)
is still required before Phase 2 is fully trusted.

## ADR-007 — organization_members as an explicit join table with a role column (2026-09-13)

**Decision:** Model the user↔organization relationship as its own mapped
entity (`OrganizationMember`: `organization_id`, `user_id`, `role`), not a
plain SQLAlchemy `secondary=` many-to-many table.

**Why:** The association already needs an attribute (`role`) beyond the
two foreign keys, and later phases (RBAC, audit events referencing "who
did this in which org") will want to reference a membership row directly.
A `secondary=` table can't carry extra columns or be referenced by ID.

**Alternative considered:** Put a single `role`/`organization_id` directly
on `User` — rejected because it silently assumes a user belongs to exactly
one organization, which contradicts the spec's multi-tenant model.

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

## ADR-006 — Phase 2 network/Docker verification gap persists (2026-09-13)

**Context:** Same sandbox restriction as ADR-005, re-confirmed for Phase 2:
`pypi.org`/`files.pythonhosted.org` return `403 host_not_allowed`,
`archive.ubuntu.com` (tried as a fallback for `python3-asyncpg`/
`python3-alembic`/a newer `python3-sqlalchemy`) also returns 403 on every
package fetch, no local wheel cache has the needed packages, and no Docker
daemon is running.

**What was different this phase:** PostgreSQL 16 is installed as a system
package in this sandbox (unlike the other infra services). It was started
locally (`service postgresql start`) with an `agentabi`/`agentabi_test`
database, making real Postgres available for verification even though the
Python driver stack (SQLAlchemy/asyncpg/Alembic) could not be installed —
see ADR-008 for how that was used.

**Action for the user:** same as ADR-005 — run `make install && make lint
&& make typecheck && make test` in an environment with normal PyPI/Docker
access before treating Phase 2 as fully proven.

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
