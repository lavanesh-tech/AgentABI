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

## Phase 3: Component Registry

```
backend/
  alembic/versions/
    0002_component_registry.py  # components, component_versions, immutability trigger
  app/
    domain/
      enums.py                   # ComponentType, ComponentStatus
      exceptions.py               # AgentABIError hierarchy (Not Found / Conflict / Invalid)
      checksums.py                 # canonicalize_content(), compute_checksum() (SHA-256)
      component_content.py         # per-ComponentType Pydantic content models + validate_content()
    models/
      component.py                 # Component (identity)
      component_version.py         # ComponentVersion (immutable snapshot)
    repositories/
      project_repository.py        # get_by_id (existence check only)
      component_repository.py
      component_version_repository.py
    services/
      component_registry.py        # ComponentRegistryService — all business rules
    api/v1/
      components.py                # routes + request/response schemas
      errors.py                    # domain exception -> HTTP response, registered once
  tests/
    test_checksums.py               # pure unit tests
    test_component_content.py        # pure unit tests
    test_component_registry_service.py  # real-Postgres integration tests
    test_components_api.py               # real-Postgres HTTP integration tests
```

### Why this shape

- **Generic `components` + `component_versions`, not one table per
  component type.** All ten component types share the same identity/
  versioning lifecycle (create, version, list, get-latest); only their
  *content* shape differs, and that's handled by JSONB + per-type Pydantic
  validation instead of ten near-identical tables. See ADR-009 for the
  tradeoff this trades away.
- **`sequence` (a Postgres `IDENTITY` column) instead of a
  `latest_version_id` pointer on `components`.** An earlier design
  considered a denormalized "latest version" foreign key on `components`,
  but that requires a circular FK between `components` and
  `component_versions` (created in two migration steps) and a
  read-modify-write on every version insert. A monotonically increasing
  `sequence`, indexed as `(component_id, sequence DESC)`, gives the same
  O(log n) "latest version" lookup via a plain `ORDER BY ... LIMIT 1` with
  none of that complexity — see ADR-010.
- **Version immutability enforced twice, not just documented.** The
  service layer has no `update_component_version`/`delete_component_version`
  method at all (nothing to call even if a route wanted to). Independently,
  a Postgres trigger (`prevent_component_version_mutation`) rejects any
  `UPDATE` that changes `content` or `checksum`, so even a write that
  bypasses the ORM/service entirely is blocked. `metadata` (non-semantic,
  e.g. annotations) is intentionally left mutable. See ADR-011.
- **Checksums computed from canonicalized content only** — sorted-key,
  compact-separator JSON, SHA-256 — never from `id`/`created_at`/`sequence`,
  so identical semantic content always produces the same checksum
  regardless of key order, and two versions with the same content
  (potentially on different components) provably hash the same. See
  ADR-012.
- **Repositories introduced for the first time in this phase**
  (`ComponentRepository`, `ComponentVersionRepository`, a minimal
  `ProjectRepository`), each a thin, single-entity query surface with zero
  business logic — duplicate detection, tenant scoping, and content
  validation all live in `ComponentRegistryService`. Phase 1/2 deliberately
  had no repository layer because nothing needed one yet; this phase does
  (the service needs the same handful of queries from multiple methods).
- **`organization_id` denormalized onto `components`.** Set once from
  `project.organization_id` at creation and never changed, so
  tenant-scoped queries and the future Neo4j sync (Phase 4) don't need a
  join through `projects` just to filter by organization.
- **Domain exceptions, not scattered `try/except IntegrityError`.**
  `ComponentNotFound`, `DuplicateComponent`, `ComponentVersionNotFound`,
  `DuplicateComponentVersion`, `InvalidComponentContent`, `ProjectNotFound`
  all derive from `AgentABIError` (via `NotFoundError`/`ConflictError`).
  `app/api/v1/errors.py` maps them to HTTP responses in exactly one place,
  registered once in `main.py`; no route handler contains error-handling
  logic, and no database error text reaches the client.
- **Tenant isolation enforced in the repository query itself**
  (`WHERE component_id = ... AND project_id = ...`), not just by trusting
  the `project_id` path parameter — a component ID that exists but belongs
  to a different project returns 404, identically to an ID that doesn't
  exist at all, so cross-project probing can't distinguish the two cases.

## Phase 4: Neo4j Dependency Graph

```
backend/
  app/
    domain/
      enums.py                    # + DependencyRelationshipType (10 members)
      exceptions.py                # + GraphComponentNotFound, InvalidDependencyRelationship,
                                    #   GraphUnavailable
      relationship_rules.py        # closed (source_type, rel, target_type) allow-list
    graph/
      client.py                    # async Neo4j driver singleton, check_graph_connection(),
                                    # dispose_driver() — mirrors core/database.py's pattern
      models.py                    # ComponentNode, DependencyEdge (plain dataclasses)
      repository.py                # GraphRepository Protocol + Neo4jGraphRepository +
                                    # all Cypher + initialize_graph_schema()
    services/
      dependency_graph.py          # DependencyGraphService — sync/create/delete/list
      blast_radius.py              # BlastRadiusService — pure-Python BFS
    core/
      readiness.py                 # pluggable READINESS_CHECKS registry
    api/v1/
      graph.py                     # sync/dependencies/dependents/blast-radius routes
      health.py                    # /ready now aggregates every registered check
      errors.py                    # + InvalidDependencyRelationship (422), GraphUnavailable (503)
  tests/
    fakes.py                        # FakeGraphRepository — in-memory GraphRepository
    test_relationship_rules.py       # pure unit tests
    test_dependency_graph_service.py # service tests (real Postgres + FakeGraphRepository)
    test_blast_radius_service.py     # BFS/cycle/tenant-isolation unit tests
    test_graph_repository.py         # real-Neo4j integration tests (skip if unreachable)
    test_health.py                   # updated for the checks: {...} readiness shape
```

### PostgreSQL vs. Neo4j responsibility split

PostgreSQL (Phase 2/3) stays the single source of truth for everything a
component *is*: its identity, its versioned JSONB content, checksums,
immutability. Neo4j's only job is answering graph-shaped questions
PostgreSQL is structurally bad at: "what does X depend on," "what depends
on X," "if X changes, what's affected, how many hops away, and along which
paths." A `Component` node in Neo4j is deliberately a thin mirror of
Postgres identity columns (`component_id`, `project_id`,
`organization_id`, `component_type`, `name`, `slug`, `version`,
`checksum`, `synced_at`) — never the JSONB `content` payload itself (see
ADR-015). Sync is one explicit direction, Postgres → Neo4j
(`DependencyGraphService.sync_component`), synchronous and service-driven
rather than event-driven (Kafka-based propagation is Phase 13 — see
ADR-017); nothing ever writes Neo4j → Postgres.

### Dependency direction convention

Every edge points from the dependent component to its dependency:
`(Agent)-[:CALLS]->(Tool)` reads "Agent depends on Tool." "X's
dependencies" follows X's outgoing edges; "X's dependents" (who breaks if
X changes — the actual blast-radius question) follows X's **incoming**
edges. This is the single easiest thing in this phase to get backwards
silently, so it has its own ADR (ADR-020) plus inline comments at every
Cypher query that reads in a specific direction
(`app/graph/repository.py`'s `_LIST_DEPENDENCIES_QUERY`/
`_LIST_DEPENDENTS_QUERY`), and `BlastRadiusService` only ever calls
`list_direct_dependents`.

### Why this shape

- **A `GraphRepository` Protocol, with `Neo4jGraphRepository` as the only
  real implementation and `tests/fakes.py`'s `FakeGraphRepository` as an
  in-memory test double** — all Cypher lives behind this one interface;
  `DependencyGraphService`/`BlastRadiusService` never see a raw Neo4j
  `Record`. This is what makes the BFS/cycle/tenant-isolation logic
  independently unit-testable without a live Neo4j (see ADR-018,
  ADR-021).
- **Ten closed relationship types, validated by a centralized
  `(source_type, relationship_type, target_type)` allow-list**
  (`app/domain/relationship_rules.py`), checked once in
  `DependencyGraphService.create_dependency` before any graph write — see
  ADR-014.
- **Blast radius is pure-Python BFS over one-hop repository calls, not a
  Cypher variable-length path** — explicit `visited`-set cycle handling,
  explicit `max_depth`, deterministic (sorted) ordering, and a `path`
  recorded on every `BlastRadiusEntry` for explainability. See ADR-018 for
  the full rationale, including why this made real test coverage possible
  in an environment where a live Neo4j could not be obtained.
- **Tenant isolation enforced directly in every Cypher `MATCH` clause**
  (every node pattern includes `project_id`, not just the query's "entry"
  node), not only trusted from the URL path parameter — see ADR-019.
- **Idempotent schema initialization** (`initialize_graph_schema` —
  `CREATE CONSTRAINT ... IF NOT EXISTS` / `CREATE INDEX ... IF NOT EXISTS`
  for `component_id` uniqueness, `project_id`, and `component_type`) is
  safe to call on every app startup.
- **`app/core/readiness.py`'s pluggable check registry** replaces
  `/ready`'s old hardcoded `database: bool` with `checks: {name: bool}`,
  aggregating Postgres and Neo4j today and designed for Redis/Kafka later
  without changing the endpoint itself — see ADR-016.
- **Domain errors specific to the graph layer**
  (`GraphComponentNotFound` → 404, `InvalidDependencyRelationship` → 422,
  `GraphUnavailable` → 503) extend the existing Phase 3 exception
  hierarchy and are mapped centrally in `app/api/v1/errors.py`, exactly
  like Phase 3's component errors — no new error-handling pattern
  introduced.
- **Routes stay thin** (`app/api/v1/graph.py`): request/response Pydantic
  schemas, a service call, a response mapping — no Cypher, no direct
  driver access, no raw Neo4j types crossing the API boundary.

### Neo4j/Docker in this session

Neo4j could not be run for real in this session, in either the cloud
sandbox or (via the device bridge) the Mac — see ADR-021 for exactly what
was attempted and the exact commands to complete verification once
Neo4j/network access is available. Unlike Phases 1–3, this sandbox could
not install *any* of the project's Python dependencies this session
either (`pip`/`uv`/apt all return 403 — the same restriction as before,
re-confirmed, not new), so the actual `pytest` suite could not be run.
What *was* verified for real: ruff (format + lint) clean,
`python3.12 -m py_compile` clean on every new/changed file, and — because
`app/graph/repository.py`'s `neo4j` import was made lazy so the
`GraphRepository` Protocol is importable without the package installed —
a standalone script genuinely executing `BlastRadiusService` and
`relationship_rules` against `FakeGraphRepository`, 26/26 checks passing
(cycle termination/dedup, direction, depth, tenant isolation, determinism;
see ADR-021 for the full list). What that script could *not* cover:
`DependencyGraphService`'s `sync_component` (needs SQLAlchemy) and any
real Cypher (needs the `neo4j` driver and a reachable Neo4j) — those
remain written-but-unexecuted this session; ADR-021 has the exact
commands to complete verification once dependencies/Neo4j are reachable.
