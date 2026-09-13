# Architecture

Living document — updated as phases land. Phase 1 establishes only the
application skeleton described below.

## Phase 1: Foundation

```
docker-compose.yml        # local infra: postgres, redis, neo4j, kafka, api
backend/
  Dockerfile               # multi-stage-ready slim Python 3.12 image
  pyproject.toml           # deps, ruff, mypy, pytest config (single source)
  app/
    main.py                # FastAPI app factory + lifespan + middleware wiring
    core/
      config.py            # Settings (pydantic-settings), get_settings() singleton
      logging.py           # structlog configuration (console/json)
      middleware.py        # CorrelationIdMiddleware
    api/v1/
      router.py            # aggregates all v1 routers
      health.py            # GET /api/v1/health
    domain/ models/ repositories/ services/ compatibility/
    replay/ graph/ providers/ github/ workers/ telemetry/
                            # empty package scaffolding for later phases
  tests/
    conftest.py             # async httpx test client fixture
    test_health.py
    test_config.py
```

### Why this shape

- **`core/config.py` as the single settings source.** Every other module
  imports `get_settings()` rather than reading `os.environ`. This makes
  configuration testable (override env vars in tests) and keeps secret
  handling in one auditable place.
- **`api/v1/` versioning from day one.** Avoids an awkward breaking migration
  later when a v2 is inevitably needed (schema evolution, GitHub webhook
  payload versions, etc.).
- **Package-per-concern (`compatibility/`, `graph/`, `replay/`, `providers/`,
  `github/`, `workers/`) created empty now.** This is intentional scaffolding
  so later phases add code to an already-reviewed location instead of
  each phase inventing its own structure.
- **structlog over stdlib logging directly.** Gives structured, greppable
  JSON logs in production and readable console logs locally, with
  request-scoped correlation IDs threaded through via contextvars — needed
  later for tracing a scan/replay across async workers and Kafka consumers.
- **`CorrelationIdMiddleware`.** Every HTTP request gets (or propagates) an
  `X-Correlation-ID`; this ID will later become the trace ID handed to
  OpenTelemetry spans (Phase 15) and to Kafka event headers (Phase 13), so
  a single PR's compatibility scan is traceable end-to-end across services.
- **Health endpoint deliberately minimal.** It reports process liveness only.
  It does NOT probe Postgres/Redis/Neo4j/Kafka yet — those clients don't
  exist until Phases 2/4/13 — so it never lies about readiness it can't
  actually verify.

### Local infrastructure (docker-compose.yml)

- `postgres` (16-alpine), `redis` (7-alpine), `neo4j` (5-community, APOC
  plugin), `kafka` (Bitnami, KRaft mode — no Zookeeper) — each with a
  healthcheck.
- `api` builds from `backend/Dockerfile`, depends on all four infra services
  being `service_healthy`, and mounts `backend/app` for live-reload in dev.

### Deferred to later phases (not implemented yet)

- Any Neo4j graph schema or traversal (Phase 4)
- Any compatibility/diff logic (Phase 5)
- Any provider client (Phase 8/9)
- Any GitHub webhook handling (Phase 12)
- Any Kafka producer/consumer (Phase 13)
- OpenTelemetry instrumentation (Phase 15)

## Phase 2: PostgreSQL + SQLAlchemy + Alembic

```
backend/
  alembic.ini               # points at alembic/, sqlalchemy.url deliberately unset
  alembic/
    env.py                  # async migration env; URL comes from get_settings()
    script.py.mako          # revision template (matches project typing style)
    versions/
      0001_initial_schema.py  # organizations, users, projects, organization_members
  app/
    core/
      database.py            # async engine/session singletons, get_db_session dep,
                              # check_database_connection(), dispose_engine()
    models/
      base.py                 # Base, UUIDPrimaryKeyMixin, TimestampMixin
      organization.py
      user.py
      project.py
      organization_member.py  # org<->user association + role
    api/v1/health.py          # adds GET /api/v1/ready (real DB probe, 503 on failure)
  tests/
    test_database.py          # engine/session singleton behavior, readiness probe
    test_models.py             # constraint/cascade integration tests (real Postgres)
    test_config.py             # + DSN env-override test
    test_health.py             # + /ready 200/503 tests
```

### Why this shape

- **One `core/database.py` owning engine + session lifecycle**, not a
  repository layer. The spec explicitly says not to introduce repository
  abstractions until they earn their keep; at this phase the only consumer
  is a FastAPI dependency (`get_db_session`) and Alembic's `env.py`, so a
  thin, direct module is the honest amount of structure.
- **Server-generated UUID primary keys** (`gen_random_uuid()`, built into
  Postgres 13+ core) via `UUIDPrimaryKeyMixin`, not Python-side
  `default=uuid4`. A row inserted by anything other than this ORM (a raw
  migration, another service) still gets a correct, unique ID.
- **Server-generated, timezone-aware `created_at`/`updated_at`** via
  `TimestampMixin`, using `func.now()`/`onupdate=func.now()` — the database
  clock is the single source of truth, not each app instance's clock.
- **`organization_members` as an explicit association table with a `role`
  column**, not a bare many-to-many. Phase spec calls for org/project
  isolation now and RBAC later (Phase 20-adjacent); this gives later
  authorization code something to query without inventing a full
  permissions system today.
- **`projects.slug` unique per-organization (`UniqueConstraint(organization_id,
  slug)`), not globally.** Two different organizations may each reasonably
  have a project called "payments"; only `organizations.slug` is globally
  unique.
- **`ON DELETE CASCADE` at the database level**, mirrored by
  `cascade="all, delete-orphan"` + `passive_deletes=True` on the ORM
  relationships. Deleting an organization actually cleans up its projects
  and memberships even if the delete happens outside the ORM.
- **`/ready` split from `/health`.** `/health` still proves only process
  liveness (Phase 1). `/ready` calls `check_database_connection()`, which
  opens a real connection and runs `SELECT 1`; on failure the endpoint
  returns HTTP 503 rather than a happy-looking 200. This is what a
  Kubernetes `readinessProbe` should point at once Phase 18 exists.
- **`alembic.ini` has no `sqlalchemy.url`.** `alembic/env.py` builds the URL
  from `app.core.config.get_settings()` so migrations, the app, and tests
  all resolve the database from the exact same environment variable
  (`POSTGRES_DSN`), never a second hardcoded copy.
- **`Base.metadata.create_all()` is used only inside `tests/conftest.py`'s
  `db_engine` fixture**, to stand up a throwaway schema per test run. It is
  never used for the application's actual schema — that's what the Alembic
  migration is for (per the project's non-negotiable rules).

### Local Postgres in this session

This cloud sandbox has no reachable PyPI and no running Docker daemon (see
`docs/DECISIONS.md` ADR-005/006 for the network-policy details), but it
does have PostgreSQL 16 installed as a system package. It was started
(`service postgresql start`) and an `agentabi` role + `agentabi`/
`agentabi_test` databases were created locally to make real integration
verification possible for this phase (see Verification below). This is a
sandbox-only convenience — the checked-in `docker-compose.yml` Postgres
service (from Phase 1) remains how the project actually runs Postgres in
local development and CI.
