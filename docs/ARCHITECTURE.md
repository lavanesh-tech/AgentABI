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

## Phase 5: Compatibility / Schema-Diff Engine

```
backend/
  app/
    compatibility/
      models.py               # Direction, ChangeType (~40), Classification, Severity,
                               # CompatibilityStatus; Change + AnalysisResult dataclasses
      schema_normalizer.py     # normalize_schema() — stable ordering, both nullable
                               # conventions collapsed, bounded recursion depth
      rules.py                 # classify()/classify_constraint_change()/derive_status() —
                               # the only place a (ChangeType, Direction) becomes a verdict
      diff.py                  # diff_schemas() (directional, structural) + diff_mapping()
                               # (generic, non-directional) + sort_changes()
      analyzer.py              # analyze(component_type, baseline, candidate) — dispatches
                               # to one function per supported ComponentType
    models/
      compatibility_scan.py    # CompatibilityScan ORM model (+ summary count columns)
      scan_change.py           # ScanChange ORM model (change_type: VARCHAR, not enum)
    repositories/
      compatibility_scan_repository.py
    services/
      compatibility_service.py # CompatibilityService — load versions, dispatch to
                                # analyze(), persist scan + changes, no ORM in the diff path
    api/v1/
      compatibility.py         # POST/GET scans, GET scan, GET scan changes
      errors.py                 # + InvalidCompatibilityComparison, UnsupportedCompatibilityType,
                                 # SchemaNormalizationError (all 422)
  alembic/versions/
    0003_compatibility_scans.py # compatibility_scans, scan_changes, 3 new enums,
                                 # prevent_compatibility_evidence_mutation() trigger
  tests/
    test_schema_normalizer.py    # pure unit tests
    test_rules.py                 # pure unit tests
    test_diff.py                  # pure unit tests (incl. the spec's acceptance case)
    test_analyzer.py              # pure unit tests, one per supported ComponentType
    test_compatibility_service.py # real-Postgres integration tests
    test_compatibility_api.py     # real-Postgres + HTTP integration tests
```

### The engine is deterministic software, not an LLM call

`app/compatibility/` has no LLM client, no prompt, no model call anywhere
in its import graph. Every verdict — classification, severity, status —
comes from `rules.py`'s lookup tables, applied to structural facts
`diff.py` computed. This is the phase's one non-negotiable constraint: a
compatibility result must be reproducible from the same two inputs, today
and in five years, without depending on model behavior. LLM-generated
*explanations* of a scan are an explicit later-phase concern (see
ROADMAP.md); Phase 5 only produces the facts they'd explain.

### Direction is explicit, never inferred

`Direction.INPUT` / `Direction.OUTPUT` / `Direction.NEUTRAL` is threaded
through every call to `diff_schemas()`/`classify()`. `analyzer.py` decides
the direction by which field of a component's content a schema comes from
(`input_schema` → `INPUT`, `output_schema` → `OUTPUT`; a standalone
`SCHEMA` component → `NEUTRAL`) — never by guessing from field names.
Removing a required field is compatible on the input side (existing
callers already satisfy the old, stricter contract) and breaking on the
output side (existing consumers may read that field); adding one is the
mirror image. See ADR-023 for the full rules table and the one case
(`REQUIRED_FIELD_ADDED` + `INPUT`) reserved for `Severity.CRITICAL`.

### Normalization is not the same job as Phase 3's checksum

Phase 3's `checksum` (ADR-012) answers "did the content change at all,"
computed from canonicalized JSON — sufficient for change *detection*, not
for change *explanation*. `schema_normalizer.normalize_schema()` exists
because two schemas that mean the same thing can differ in
non-semantic ways (property/required-list ordering, `type: "string"` vs.
`type: ["string"]`, duplicate enum values) that must be collapsed before
diffing — but never in semantic ways: two nullability spellings
(`type: [T, "null"]` and OpenAPI-3.0's `nullable: true`) are recognized as
the same concept, not merged away as "irrelevant metadata." Both
`normalize_schema` and `diff_schemas` cap recursion at `_MAX_DEPTH = 64`
and fail closed (`SchemaNormalizationError`) rather than overflowing the
stack on pathological input.

### Compatibility status vs. deployment risk

`CompatibilityStatus` (`COMPATIBLE`/`WARNING`/`BREAKING`) is a fact about
what changed between two versions, derived deterministically from the
worst classification among a scan's changes (`derive_status()`). It is
**not** a deployment gate — Phase 5 never returns PASS/WARN/BLOCK. That
decision belongs to the Phase 11 Risk Engine, which will combine this
evidence with blast radius (Phase 4) and replay/behavioral results
(Phases 7/10) — a change classified `BREAKING` here might still be a safe
deploy if blast radius is zero.

### Why this shape

- **Component-specific dispatch (`analyzer.py`'s `_DISPATCH` dict), not
  one diff function forced onto every `ComponentType`** — Tool/MCP/Schema
  get full structural `diff_schemas()`; Prompt/Model/Agent get targeted
  field-by-field comparisons matching what their `*Content` models
  actually represent; Workflow/Policy/API fall back to generic
  `diff_mapping()` where Phase 3 didn't model a fixed structure (see
  ADR-025). `PROVIDER` has no comparison defined at all yet —
  `UnsupportedCompatibilityType`, not a silent no-op.
- **`app/compatibility/` imports nothing from SQLAlchemy, Pydantic, or
  FastAPI** — every function in `models.py`/`schema_normalizer.py`/
  `rules.py`/`diff.py`/`analyzer.py` takes and returns plain dataclasses
  and stdlib types. This is what let the core engine run through the real
  `pytest` binary this session despite the sandbox's dependency
  restrictions (see ADR-022) and is what keeps the diff engine reusable
  by later phases (GitHub check-runs, LLM explanation generation) without
  those callers pulling in a database session.
- **`change_type` persisted as `VARCHAR`, `classification`/`severity`/
  `status` as native Postgres enums** — the former is an open, growing
  set (~40 members and climbing); the latter three are closed and stable.
  See ADR-024.
- **Immutable by construction and by trigger** — `CompatibilityService`
  exposes no update/delete method, and `prevent_compatibility_evidence_
  mutation()` rejects any `UPDATE` on either table at the database level,
  unconditionally (stricter than Phase 3's content-only trigger — see
  ADR-024). A scan is audit evidence for a release decision; it does not
  change after the fact.
- **Every `run_scan` call creates a new historical scan row** — a
  deliberate idempotency choice, not an accidental side effect of missing
  a uniqueness constraint (ADR-024).
- **The same-component rule is enforced twice** — structurally, by
  `run_scan`'s single-`component_id` signature, and defensively, by an
  explicit runtime check in `_scan_from_versions` (ADR-024).
- **Deterministic output ordering** — `sort_changes()` sorts by
  `(path, change_type, classification)` and the result is persisted via an
  explicit `order_index` column, never re-derived from insertion order or
  a query's `ORDER BY` at read time.
- **Routes stay thin** (`app/api/v1/compatibility.py`): Pydantic
  schemas, a service call, a response mapping — no comparison logic, no
  ORM objects crossing the API boundary.

### Verification in this session

The compatibility engine is plain-dataclass, stdlib-only Python, so it
could be run through the real, already-installed standalone `pytest`
binary via `pytest --noconftest` (bypassing `tests/conftest.py`'s
`httpx` import) — **75/75 pure unit tests passed**
(`test_schema_normalizer.py`, `test_rules.py`, `test_diff.py`,
`test_analyzer.py`), including the spec's exact acceptance-case example
run through the generic engine, not hardcoded. `ruff format --check` /
`ruff check` are clean and `python3.12 -m py_compile` succeeds on every
new/changed file. Migration 0003 was verified by direct DDL execution
against a real local Postgres 16 (same ADR-008 pattern as every prior
phase's migration) — the immutability triggers, cascade deletes, and a
full insert/read round-trip of the spec's acceptance-case data all
behaved as expected. `test_compatibility_service.py` and
`test_compatibility_api.py` are written and `py_compile`-clean but could
not be executed through `pytest` itself this session (need SQLAlchemy/
FastAPI/httpx, unavailable — same restriction as every prior phase). See
ADR-022 for the full account.

## Phase 6: Trajectory Recording

```
backend/
  app/
    trajectory/
      models.py               # EventType (18-member StrEnum), TrajectoryStatus,
                               # payload dataclasses: ModelRequestPayload,
                               # ModelResponsePayload, ToolCallPayload,
                               # ToolResponsePayload, StatePayload
      transitions.py           # is_valid_transition()/is_terminal() — the one place
                               # RUNNING→COMPLETED/FAILED rules live
      redaction.py              # sanitize() — recursive, deterministic secret redaction
      payload_limits.py         # enforce_payload_limit() — soft-limit truncation,
                                 # hard-limit rejection (TrajectoryPayloadTooLarge)
      hashing.py                 # compute_event_hash() — reuses Phase 3's
                                  # canonicalize_content() + SHA-256
      validation.py               # validate_event_shape() — reserved event types,
                                   # required-field rules per EventType
    models/
      trajectory.py            # Trajectory ORM model (mutable status/next_sequence)
      trajectory_event.py       # TrajectoryEvent ORM model (append-only evidence)
    repositories/
      trajectory_repository.py # add()/add_event(), atomic allocate_sequence(),
                                # atomic transition_status(), ordered list_events()
    services/
      trajectory_recorder.py   # TrajectoryRecorderService — start/append/complete/
                                # fail/get/list, component-version validation,
                                # redaction + size-limit + idempotency orchestration
    api/v1/
      trajectories.py          # start, append event, complete, fail, get, list
                                # trajectory, list ordered events
      errors.py                 # + InvalidTrajectoryEvent, TrajectoryPayloadTooLarge
  alembic/versions/
    0004_trajectories.py      # trajectories, trajectory_events, 2 new enums,
                               # partial unique indexes (external_run_id,
                               # external_event_id), prevent_trajectory_event_mutation()
                               # trigger (trajectory_events only)
  tests/
    test_trajectory_transitions.py       # pure unit tests
    test_trajectory_redaction.py          # pure unit tests (incl. spec's secret case)
    test_trajectory_payload_limits.py      # pure unit tests
    test_trajectory_validation.py           # pure unit tests
    test_trajectory_hashing.py               # pure unit tests
    test_trajectory_models.py                 # pure unit tests
    test_trajectory_recorder_service.py        # real-Postgres integration tests
    test_trajectories_api.py                    # real-Postgres + HTTP integration tests
```

### Trajectory recording is evidence capture, not summarization

Nothing in `app/trajectory/` calls a model or produces a natural-language
description of a run. A trajectory is a strongly-typed, ordered sequence
of `TrajectoryEvent` rows — the raw material Phase 7's replay engine will
consume. `EventType` is a closed 18-member enum precisely so that no part
of the system ever has to pattern-match a free-form string to know what
kind of thing happened.

### Sequence allocation: one atomic UPDATE, never `max()+1`

`TrajectoryRepository.allocate_sequence()` issues a single statement:

```sql
UPDATE trajectories
   SET next_sequence = next_sequence + 1
 WHERE id = :id AND status = 'running'
RETURNING next_sequence;
```

Postgres serializes concurrent `UPDATE`s to the same row, so two
concurrent appenders can never receive the same sequence number — the
classic "`SELECT max(sequence)+1` then `INSERT`" race (two readers see the
same max, both insert `+1`, one either collides or silently overwrites
ordering) is structurally impossible here. Folding `WHERE status =
'running'` into the *same* statement also closes the TOCTOU race between
"check the trajectory is still running" and "allocate a sequence number"
— a trajectory that completes or fails between those two steps in another
request simply fails to allocate (`allocate_sequence()` returns `None`),
rather than silently accepting a post-terminal event. See ADR-026.

### Two different immutability postures, on purpose

`trajectory_events` gets an unconditional `BEFORE UPDATE` trigger
(`prevent_trajectory_event_mutation()`, same shape as Phase 5's
`prevent_compatibility_evidence_mutation()`): once recorded, historical
evidence never changes. `trajectories` gets **no** trigger at all — its
`status`, `completed_at`, `error`, and `next_sequence` columns are
expected to mutate over the row's `RUNNING` lifetime, exactly the way
Phase 3's `components` identity table (mutable) differs from
`component_versions` (immutable, ADR-011). The service layer, not the
database, is what keeps `Trajectory` mutation narrow — only
`transition_status()` and `allocate_sequence()` ever `UPDATE` the row.
See ADR-027.

### Component-version snapshot linkage

A `TrajectoryEvent` may reference `component_version_id` (the exact
immutable version active when the event occurred), not just a mutable
`component_id`. `TrajectoryRecorderService._resolve_component_reference()`
validates that a given version actually belongs to the resolved
component and to the trajectory's own project before the event is ever
persisted — cross-project version references are rejected the same way
Phase 3/5 reject cross-project component references.

### Dual idempotency, one comparison mechanism

Trajectory-start idempotency keys on `(project_id, external_run_id)` (a
partial unique index, `WHERE external_run_id IS NOT NULL`): an exact
retry (same `external_run_id`, same identifying fields) returns the
existing trajectory; a retry with the same id but different data raises
`TrajectoryAlreadyExists`. Event-append idempotency keys on
`(trajectory_id, external_event_id)` the same way, but uses the event's
own `content_hash` (ADR-028) as the "is this really the same event"
comparator instead of a second bespoke comparison — an exact-hash retry
returns the existing event with no new row and no sequence consumed; a
hash mismatch raises `DuplicateTrajectoryEvent`. See ADR-029.

### Redaction and payload-size limits are foundations, not a DLP platform

`redaction.sanitize()` recurses through dicts/lists/tuples, redacting any
key that case/hyphen-insensitively matches a small fixed set
(`password`, `secret`, `token`, `api_key`, `authorization`,
`access_token`, `refresh_token`) — deterministic, not a general secret
scanner. `payload_limits.enforce_payload_limit()` is a two-tier
soft/hard limit: under 32KB, stored in full; between 32KB and 1MB,
replaced with a deterministic truncated representation (`_truncated`,
`_original_size_bytes`, `_preview`); over 1MB, rejected outright
(`TrajectoryPayloadTooLarge`). Redaction always runs before size
enforcement, so a payload can never be rejected or truncated because of
bytes that get redacted away anyway. Archival of oversized payloads to
S3/object storage is explicitly out of scope for this phase — see
ADR-030.

### Why this shape

- **Dataclasses, not Pydantic, for `app/trajectory/`** — mirrors Phase
  5's `app/compatibility/` choice: zero SQLAlchemy/Pydantic/FastAPI
  imports in the pure-logic package keeps it testable through the real,
  installed `pytest` binary via `--noconftest`, independent of which
  dependencies happen to be installable in a given environment.
- **`RUN_COMPLETED`/`RUN_FAILED` reserved, not accepted via
  `append_event()`** — trajectory completion/failure is a status
  transition with its own invariants (terminal-state enforcement,
  `completed_at` stamping), not just another row; routing it through the
  dedicated `complete_trajectory()`/`fail_trajectory()` methods keeps
  that invariant in one place instead of duplicated between "generic
  event append" and "status change."
- **No update/delete on `TrajectoryEvent`, anywhere in the service** —
  the append-only contract is enforced twice: once by never writing the
  code path, once by the database trigger, for the same defense-in-depth
  reason Phase 3 validates versions immutable at both layers (ADR-011).

### Verification in this session

The entire `app/trajectory/` package is dataclass/stdlib-only, so it ran
through the real, already-installed standalone `pytest` binary via
`pytest --noconftest`: **49/49 pure unit tests passed**
(`test_trajectory_transitions.py`, `test_trajectory_redaction.py` —
including the spec's exact secret-redaction acceptance case —
`test_trajectory_payload_limits.py`, `test_trajectory_validation.py`,
`test_trajectory_hashing.py`, `test_trajectory_models.py`); combined with
Phase 5's 75 pure tests, **124/124 passed**, confirming no regression.
`ruff format` / `ruff check` are clean and `python3.12 -m py_compile`
succeeds on every new/changed file; `mypy` fails on the same
pre-existing `pydantic.mypy` plugin-import error as every prior phase
(not a new regression).

Migration 0004 was verified by direct DDL execution against a real local
Postgres 16 (same ADR-008 pattern), including a full run of the spec's
exact 8-event `checkout-run-8291` acceptance case (correct 1-8 ordering
and event types), the `trajectory_events` immutability trigger rejecting
an `UPDATE`, the `trajectories` row accepting a legitimate status
`UPDATE` (no trigger), the `(trajectory_id, sequence_number)` unique
constraint rejecting a duplicate, the partial `(project_id,
external_run_id)` unique index rejecting a same-project duplicate while
allowing the same id in a different project, and `ON DELETE CASCADE`
from `projects` removing a trajectory's events. While fixing the
`conftest.py` fixture for this phase's trigger, a latent gap from Phase 5
was found and fixed: `_IMMUTABILITY_DDL` had never been extended for
`prevent_compatibility_evidence_mutation()`, so Phase 5's two immutability
tests would have silently failed had SQLAlchemy ever been installable to
run them — see ADR-031.

`test_trajectory_recorder_service.py` (24 tests, incl. a real
`asyncio.gather` concurrent-append test asserting distinct sequence
numbers, and the generic-engine acceptance case) and
`test_trajectories_api.py` (16 tests) are written and `py_compile`-clean
but could not be executed through `pytest` itself this session (need
SQLAlchemy/FastAPI/httpx, unavailable — same restriction as every prior
phase). See ADR-032 for the full account.

## Phase 7: Deterministic Replay Engine

```
backend/
  app/
    replay/
      models.py       # ReplayStatus, StepKind, StepStatus, TrajectoryEventView,
                       # ReplayPlanStep, ReplayPlan, ExecutionOutcome
      transitions.py    # is_valid_transition()/is_terminal() for ReplayStatus
      planner.py          # build_replay_plan() — pure, deterministic classification
      executor.py           # ReplayExecutor Protocol, ExecutorRegistry, FakeReplayExecutor
    models/
      replay_run.py    # ReplayRun ORM model (mutable status, like Trajectory)
      replay_step.py     # ReplayStep ORM model (append-only, like TrajectoryEvent)
    repositories/
      replay_repository.py # atomic transition_status(), ordered list_steps()
    services/
      replay_service.py    # ReplayService — create/execute/get/list, plan
                            # serialization, executor dispatch, idempotency
    api/v1/
      replays.py       # create, list, get, execute, list steps
      errors.py          # + InvalidReplaySubstitution, ReplayExecutorUnavailable,
                          # ReplayExecutionFailed
  alembic/versions/
    0005_replays.py    # replay_runs, replay_steps, 3 new enums, partial unique
                        # idempotency index, prevent_replay_step_mutation() trigger
  tests/
    test_replay_transitions.py  # pure unit tests
    test_replay_planner.py        # pure unit tests (incl. the spec's acceptance case)
    test_replay_executor.py         # pure unit tests (FakeReplayExecutor/registry)
    test_replay_service.py            # real-Postgres integration tests
    test_replays_api.py                 # real-Postgres + HTTP integration tests
```

### Replay is plan-then-execute, never trajectory→LLM→guessed outcome

`ReplayService.create_replay()` only builds and persists a deterministic
plan (`app/replay/planner.py`); no execution happens until a separate
`execute_replay()` call. Nothing in either path calls a model — the plan
decides what's reused, substituted, or provider-required from structural
facts (event type, component/version identity) the same way Phase 5's
`rules.py` decides compatibility classifications: lookup logic over
recorded facts, not judgment calls.

### Classification: substitute, skip, reuse, or defer to a provider

`build_replay_plan()` walks a trajectory's events in `sequence_number`
order (never timestamp order) and classifies each one: an invocation
event (`TOOL_CALL`/`MCP_REQUEST`/`API_REQUEST`) matching the baseline
component *and* version being replaced becomes `SUBSTITUTED_EXECUTION`
(re-run with the candidate, historical arguments preserved verbatim);
its paired response (matched by `invocation_id`) becomes `SKIPPED`,
explicitly justified as superseded — keeping the baseline's response as
if it were the replay's own result would misrepresent what happened.
`MODEL_REQUEST`/`MODEL_RESPONSE` become `PROVIDER_EXECUTION_REQUIRED`:
Phase 7 has no provider adapter (Phase 8/9), so it names the gap rather
than fabricating a response. Everything else — a different component's
invocation, state events, agent lifecycle events — is `REUSED_EVIDENCE`,
carried forward unchanged. A plan with zero substituted steps (the
baseline was never actually invoked) is rejected outright
(`InvalidReplaySubstitution`) rather than silently producing a no-op
replay.

### Plan-then-insert-once, not insert-then-update

A `ReplayRun`'s `plan` (JSONB) is computed once at creation and never
recomputed; `execute_replay()` walks that stored plan and inserts each
`ReplayStep` exactly once, already in its final status — never insert a
`PENDING` row and later `UPDATE` it to `EXECUTED`/`FAILED`. This is what
lets `replay_steps` carry the same unconditional immutability trigger as
Phase 6's `trajectory_events` with no contradiction: nothing ever needs
to mutate a step after the fact. `replay_runs` gets no trigger, mirroring
Phase 6's `trajectories`/ADR-027 split — its `status`/`started_at`/
`completed_at`/`error` genuinely change over the run's lifecycle,
protected only by `ReplayService` never exposing another mutation path.

### Execution boundary: no executor wired means an explicit failure

`ExecutorRegistry` ships empty in production wiring — Phase 7 has
nothing real to execute yet (tool/MCP/API integrations and provider
adapters are later phases). Reaching a `SUBSTITUTED_EXECUTION` step with
no matching executor deterministically raises
`ReplayExecutorUnavailable` and marks the run `FAILED`, rather than
silently skipping the step or fabricating a result. `FakeReplayExecutor`
is the only implementation this phase ships: deterministic, in-memory,
records every invocation, never touches a network — used exclusively in
tests to prove the orchestration (candidate invoked, not baseline;
historical arguments preserved; original trajectory untouched).

### Why this shape

- **Dataclasses/Protocol, not Pydantic/ABC, for `app/replay/`** —
  mirrors Phase 5/6's testability choice: zero SQLAlchemy/Pydantic/
  FastAPI imports keeps the planner and executor contract runnable
  through the real installed `pytest` binary via `--noconftest`.
- **A structured `ExecutionOutcome(status="failed", ...)` is normal
  evidence; an executor *raising* is `ReplayExecutionFailed`** — the
  former is the candidate genuinely failing (recorded, replay stops,
  never falls back to historical output); the latter is a
  transport/programming error, distinct enough to need its own domain
  error.
- **Idempotency mirrors Phase 6 exactly** — `idempotency_key` on
  `ReplayRun`, a partial unique index per project, "exact match returns
  existing, conflict rejects" — reusing ADR-029's pattern rather than
  inventing a second idempotency scheme.

### Verification in this session

`app/replay/` is dataclass/`Protocol`-only, so it ran through the real,
already-installed standalone `pytest` binary via `pytest --noconftest`:
**25/25 new pure unit tests passed** (`test_replay_transitions.py`,
`test_replay_planner.py` — including the spec's exact 7-event checkout
acceptance case proving v6 is invoked with v5's historical arguments
while the original trajectory stays untouched — `test_replay_executor.py`);
combined with Phase 5/6's 124, **149/149 passed**, confirming no
regression. `ruff format --check`/`ruff check` clean;
`python3.12 -m py_compile` clean on every file; `mypy` fails on the same
pre-existing `pydantic.mypy` plugin-import error as every prior phase.

Migration 0005 was verified by direct DDL execution against a real local
Postgres 16 (same ADR-008 pattern): the acceptance case's 7-step replay
plan persisted in deterministic sequence order; the substituted step
correctly referencing candidate v6 while the original `trajectory_events`
row stayed at baseline v5 with its original output; the
`replay_steps` immutability trigger rejecting an `UPDATE`; `replay_runs`
accepting a legitimate status `UPDATE` (no trigger, by design); the
`(replay_run_id, sequence_number)` unique constraint rejecting a
duplicate; the partial `(project_id, idempotency_key)` unique index
rejecting a same-project duplicate while allowing the same key in a
different project; and `ON DELETE CASCADE` from `trajectories` removing
a replay run and its steps. `test_replay_service.py` (10 tests) and
`test_replays_api.py` (9 tests) are written and `py_compile`-clean but
could not be executed through `pytest` itself this session (need
SQLAlchemy/FastAPI/httpx, unavailable — same restriction as every prior
phase).

## Security Phase A: Authentication Foundation

```
backend/
  app/
    auth/
      claims.py        # JWTClaims dataclass — sub/iss/aud/iat/exp/org_id;
                        # no role claim (see "Role is reloaded, not embedded")
      jwt.py             # encode_token()/decode_token() — stdlib-only HS256
      principal.py         # AuthenticatedPrincipal — the typed context routes use
    api/deps/
      auth.py           # get_current_user / require_authenticated_user
    api/v1/
      auth.py           # GET /auth/me
      errors.py           # + AuthenticationError handler (401, WWW-Authenticate)
    repositories/
      user_repository.py               # get_by_id
      organization_member_repository.py # get_for_user_and_organization
    domain/exceptions.py # + AuthenticationError and its 5 subclasses
  tests/
    test_auth_jwt.py       # pure unit tests (incl. alg-confusion/tamper cases)
    test_auth_principal.py   # unit tests (needs SQLAlchemy for OrganizationRole)
    test_auth_api.py           # real-Postgres + HTTP integration tests
```

No new models and no migration: Phase 2's `User` (`is_active` already
present), `Organization`, and `OrganizationMember`/`OrganizationRole`
(`owner`/`admin`/`member`) already model everything Phase A needs —
reused as-is rather than duplicated. See ADR-037/038.

### Authentication vs. authorization

Phase A answers "who is this request from" — a verified JWT resolving to
a real, active `User`. It deliberately does *not* answer "is this user
allowed to do X": no role/project permission checks exist yet.
`AuthenticatedPrincipal.role` is populated when the token names an
organization the user belongs to, but nothing in Phase A reads it to
gate anything — that enforcement is Security Phase C.

### Role is reloaded from the database, never trusted from the JWT

`JWTClaims` carries no role claim. `get_current_user` always re-queries
`OrganizationMember` for the token's `org_id` on every request, so a
demotion/removal made after a token was issued takes effect on the very
next request rather than only after the token expires. See ADR-038.

### Why a stdlib-only JWT implementation

PyJWT/authlib cannot be installed in this sandbox (same PyPI-403
restriction as every prior phase's dependencies). `app/auth/jwt.py`
implements HS256 JWS compact serialization directly from `hmac`/
`hashlib`/`base64`/`json` — one fixed algorithm (never read from the
token, closing "alg: none"/algorithm-confusion attacks outright) and one
constant-time comparison (`hmac.compare_digest`). This mirrors the
existing pure-module pattern (`app/compatibility/`, `app/trajectory/`,
`app/replay/`): dependency-free, genuinely `pytest`-executable in this
environment. See ADR-037 for the tradeoff and future path.

### Why organization roles stayed OWNER/ADMIN/MEMBER

The request that started this phase named `ADMIN`/`ENGINEER`/`VIEWER` as
the required roles, but Phase 2 already shipped and migrated
`OrganizationRole` as `OWNER`/`ADMIN`/`MEMBER`. Renaming a migrated enum
column's values is a breaking schema change with no functional
justification here — every Phase A requirement (an organization-scoped
role, not a single global role on `User`, multi-organization membership)
is already satisfied by the existing enum. Kept as-is; see ADR-037.

### Verification in this session

`app/auth/jwt.py`/`claims.py` are stdlib-only, so they ran through the
real installed `pytest` binary via `pytest --noconftest`: **12/12 new
pure unit tests passed**, including tampered-signature, wrong-issuer,
wrong-audience, missing-claim, and alg-confusion cases; combined with
Phase 5/6/7's 149, **161/161 passed**, confirming no regression. `ruff
format --check`/`ruff check` clean; `python3.12 -m py_compile` clean;
`mypy` fails on the same pre-existing `pydantic.mypy` error as every
prior phase. `test_auth_principal.py` and `test_auth_api.py` (9 tests:
missing/valid/expired/malformed/unknown-user/disabled-user/out-of-org
tokens, and a response-shape assertion that only the four public fields
ever serialize) are written and `py_compile`-clean but need SQLAlchemy/
FastAPI/httpx, unavailable this session. No migration was needed or
created — `users.is_active` already exists from migration 0001.

## Security Phase B: GitHub OAuth2

```
backend/
  app/
    auth/
      oauth_state.py     # generate_state(), OAuthStateStore Protocol,
                          # RedisOAuthStateStore (prod), InMemory... (tests)
    core/
      redis.py            # get_redis_client()/dispose_redis_client() — same
                           # lazy-singleton pattern as core/database.py
    github/
      oauth_models.py     # GitHubIdentity, GitHubTokenResponse,
                           # GitHubOAuthClient Protocol (httpx-free — see below)
      oauth_client.py      # HttpxGitHubOAuthClient — the only module that
                            # calls GitHub over HTTP
    services/
      github_oauth_service.py  # GitHubOAuthService — login/callback orchestration
    api/deps/
      github_oauth.py     # wires RedisOAuthStateStore + HttpxGitHubOAuthClient
    api/v1/auth.py        # + GET /auth/github/login, GET /auth/github/callback
    models/user.py        # + github_user_id (unique), github_login
    domain/exceptions.py  # + OAuthError and 7 subclasses
  alembic/versions/
    0006_github_identity.py  # users.github_user_id/github_login
  tests/
    test_oauth_state.py         # pure unit tests (state store contract)
    test_github_oauth_service.py # orchestration tests via FakeGitHubOAuthClient
    test_github_oauth_api.py     # HTTP integration tests, GitHub mocked
```

Flow: `GET /auth/github/login` generates a random `state`, saves it
(Redis, TTL'd), and 302-redirects to GitHub with minimal scopes
(`read:user user:email` — identity + email only, no repository access).
`GET /auth/github/callback` validates+consumes `state` *before* trusting
anything else in the request, exchanges `code` for a GitHub access
token, fetches the GitHub identity, resolves/creates the AgentABI
`User` (matched by GitHub's immutable numeric id, never `login`), reads
existing `OrganizationMember` rows to decide whether an org context can
be attached, and issues a normal Phase A JWT via the same
`app/auth/jwt.py` used everywhere else — no second token design, no
GitHub token inside the JWT.

### `GitHubOAuthClient` lives split across two modules

The Protocol (`oauth_models.py`) has no `httpx` import; the real
implementation (`oauth_client.py`) does. This split exists purely so
`GitHubOAuthService` and its tests can import the Protocol type without
pulling in `httpx`, which is not installable in this sandbox — the same
reason `app/replay/executor.py`'s `ReplayExecutor` Protocol is decoupled
from any concrete executor.

### GitHub access token is never persisted

`token.access_token` from `exchange_code()` is used exactly once, to
call `fetch_identity()`, and then goes out of scope. It is never written
to the database, never logged (not a bound `structlog` field anywhere),
and never appears in `GitHubCallbackResponse` — only the AgentABI JWT
does. See spec §12; revisited if/when a future phase needs GitHub API
access on the user's behalf (would require explicit encrypted storage).

### Organization membership resolution — see ADR-040

Zero or multiple `OrganizationMember` rows both yield
`organization_id=None` on the issued JWT — no automatic org join, no
silently granted role. See ADR-040 for the full reasoning.

### OAuth state — see ADR-039

State validation failures (missing/malformed/expired/reused/mismatched)
are tested distinctly at the store level but collapse to one
`OAuthStateInvalid` error at the service/API boundary, mirroring
`InvalidToken`'s precedent. `RedisOAuthStateStore` fails closed
(`OAuthStateStoreUnavailable`, HTTP 503) rather than silently skipping
validation if Redis is unreachable.

### Verification in this session

`app/auth/oauth_state.py` has no SQLAlchemy/FastAPI/redis import, so it
ran through the real `pytest` binary via `pytest --noconftest`: **8/8
new pure unit tests passed** (random/unique state, save-then-consume,
one-time use, missing/malformed/expired/mismatched state). Combined with
every other pure test file in the suite, **189/189 passed**, confirming
no regression. `ruff format --check`/`ruff check` clean; `python3.12 -m
py_compile` clean across `app`, `tests`, and the new migration; `mypy`
fails on the same pre-existing `pydantic.mypy` error as every prior
phase. `test_github_oauth_service.py` (8 tests, via
`FakeGitHubOAuthClient` — no real GitHub call) and
`test_github_oauth_api.py` (5 tests, GitHub mocked via dependency
override) are written and `py_compile`-clean but need SQLAlchemy/
FastAPI/httpx, unavailable this session — same bucket as
`test_auth_api.py`/`test_replays_api.py`. Migration `0006`'s DDL (add columns, unique constraint, index, and the
downgrade) was verified by direct execution against a real local
Postgres 16 (same ADR-008 pattern as prior phases): existing rows keep
NULL `github_user_id`/`github_login` unaffected, multiple NULLs coexist,
linking a second user to an already-linked `github_user_id` is rejected
by the unique constraint, and downgrade cleanly removes both columns.
Run `alembic upgrade head` against the full migration chain to confirm
end-to-end.

## Security Phase C: RBAC and Tenant Isolation

```
backend/
  app/
    authz/
      permissions.py   # Permission enum + ROLE_PERMISSIONS (pure, no ORM)
      membership.py     # authorize_role_change() — membership-mutation policy (pure)
      context.py          # AuthorizationDecision — audit-prep struct (pure)
      service.py            # AuthorizationService — the DB-backed decision point
    api/deps/
      authz.py         # require_project_permission()/require_organization_permission()
    api/v1/
      projects.py       # minimal Project CRUD — new, authorization-testing surface
    services/
      project_service.py # minimal Project CRUD business logic
    repositories/
      project_repository.py  # + get_for_organization, get_by_slug, list_by_organization, add
    domain/exceptions.py  # + AuthorizationError, PermissionDenied,
                           #   OrganizationAccessDenied, ProjectAccessDenied, DuplicateProject
  tests/
    test_authz_permissions.py       # pure — full role x permission matrix
    test_authz_membership.py         # pure — membership-mutation policy
    test_authz_service.py              # DB integration — stale-JWT, cross-org, removal
    test_organization_isolation_api.py # HTTP integration — full isolation + role matrix
```

Authentication (Phases A/B) answers "who is this request from." Phase C
answers "what is this identity allowed to do" — a separate question,
deliberately: `AuthenticatedPrincipal` (Phase A) is unchanged, and
nothing in Phase C touches how a JWT is issued or validated.

### One dependency guards every project-scoped route

Every existing project-scoped router (`components.py`, `compatibility.py`,
`trajectories.py`, `replays.py`, `graph.py`) is already mounted under
`/projects/{project_id}/...`. `require_project_permission(Permission.X)`
(`app/api/deps/authz.py`) reads that same `project_id` path parameter,
so one dependency factory, applied via `dependencies=[...]` on each
route, authorizes all of them — no per-route authorization code, no
resource-type-specific traversal logic. A component version, a scan, a
trajectory event, a replay step never gets its own authorization
dependency: it's only ever reached through a `project_id`-scoped route,
and every repository already scopes its resource lookups by
`project_id` (e.g. `ComponentRepository.get_by_id(project_id,
component_id)`, from Phase 3), so a resource ID from another project
can never resolve even after the project-level check passes. This is
how `ComponentVersion -> Component -> Project -> Organization` and
`Replay -> Project -> Organization` traversal (spec §9) is enforced
without writing traversal code for each resource type.

### Centralized permission model

`app/authz/permissions.py` maps `OWNER > ADMIN > MEMBER` to explicit
`Permission` sets — nothing anywhere compares `role ==
OrganizationRole.ADMIN`. MEMBER is read-only across every
organization-scoped resource; ADMIN adds every engineering write
(create/update projects, register components, execute scans/replays,
mutate the graph); OWNER adds `MEMBERSHIP_MANAGE`/`ORG_MANAGE`. Kept
deliberately keyed by the role's string value, not the
`OrganizationRole` enum itself, so this module stays dependency-free
(no SQLAlchemy import) — see its docstring.

### Role is reloaded from the database for the *resource's* organization

Never `AuthenticatedPrincipal.role` (which reflects the JWT's `org_id`,
possibly a different organization than the one being accessed) and
never a caller-supplied `organization_id`. `AuthorizationService`
resolves a project's `organization_id` from the database, then queries
`OrganizationMember` fresh for that organization — every call is
independently correct for its own target, so a role checked for
organization A is never reused to authorize organization B (spec §18).
This is why a demotion or membership removal in Postgres takes effect
on a still-valid JWT's very next request, proven directly by
`test_authz_service.py`'s stale-role and membership-removal tests
(spec §25/§26 — extends ADR-038's same guarantee from role-reload to
full authorization).

### Cross-tenant denial is 404; in-tenant permission denial is 403

See ADR-042.

### Membership management: policy exists, no route yet

`app/authz/membership.py`'s `authorize_role_change` is the decision
function a future membership-mutation route would call — only OWNER
may change any membership, and even OWNER cannot demote/remove an
organization's last OWNER. No route exists yet (spec §16 explicitly
scopes this to "authorization foundation," not a shipped API); the
documented future route is `PATCH /organizations/{organization_id}/
members/{user_id}`. See ADR-041 for why ADMIN gets no partial
membership capability.

### Audit preparation, not audit logging

`AuthorizationService` builds a structured `AuthorizationDecision`
(actor, organization, resource type/id, permission, allow/deny) on
every check and logs it via the existing `structlog` setup — it is not
persisted. Security Phase E adds the audit-event table and writes these
rows there; Phase C only makes sure every field that table will need
already exists as a typed value at the decision point (spec §20).

### Verification in this session

`app/authz/permissions.py` and `app/authz/membership.py` have no
SQLAlchemy/FastAPI import, so they ran through the real `pytest` binary
via `pytest --noconftest`: **19/19 new pure unit tests passed**
(exhaustive role x permission cross-product, OWNER > ADMIN > MEMBER
subset proof, membership-mutation policy incl. last-owner protection).
Combined with every other pure test file in the suite, **208/208
passed**, confirming no regression. `ruff format --check`/`ruff check`
clean; `python3.12 -m py_compile` clean across `app`/`tests`; `mypy`
fails on the same pre-existing `pydantic.mypy` error as every prior
phase. `test_authz_service.py` (7 tests, incl. the mandated stale-JWT
and membership-removal tests) and `test_organization_isolation_api.py`
(17 tests: two-org/two-project isolation, direct-UUID-guessing, nested-
resource isolation across components/scans/trajectories/replays, and
the OWNER/ADMIN/MEMBER role matrix across project/component/scan/
trajectory/graph endpoints) are written and `py_compile`-clean but need
SQLAlchemy/FastAPI/httpx, unavailable this session — same bucket as
`test_auth_api.py`. No migration was needed or created — Phase C adds
no new columns/tables, only authorization logic and a minimal `Project`
CRUD surface over the existing `projects` table.

### API hardening (Security Phase D)

Redis-backed distributed rate limiting (`app/core/rate_limit.py`,
`app/api/deps/rate_limit.py`) is applied via reusable dependencies
(`rate_limit_by_user`/`rate_limit_by_client`), never hand-written Redis
calls in routes: `/api/v1/auth/github/login`, `/api/v1/auth/github/
callback` (by client identity — no user exists yet), compatibility scan
creation, replay creation/execution, and trajectory creation/append (by
user id). Algorithm and failure policy: ADR-043. Identity derivation
(user id vs. trusted-proxy-aware client IP): ADR-044.

Every error response uses one standardized envelope,
`{"error": {"code", "message", "request_id"}}` (`app/api/v1/errors.py`);
codes include `VALIDATION_ERROR`, `AUTHENTICATION_REQUIRED`,
`INVALID_TOKEN`, `TOKEN_EXPIRED`, `AUTHORIZATION_DENIED`,
`RESOURCE_NOT_FOUND`, `RATE_LIMITED`, `CONFLICT`, `REQUEST_TOO_LARGE`,
`INTERNAL_ERROR`. See ADR-045.

CORS is environment-driven, never hardcoded (`app/core/cors.py`):
`CORS_ALLOW_ORIGINS`/`CORS_ALLOW_CREDENTIALS` configure it for both dev
and production, with credentials-plus-wildcard rejected at startup.
Security headers (`app/core/security_headers.py`) add
`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` on every
response, `Strict-Transport-Security` only in production, and
`Cache-Control: no-store` on `/api/v1/auth/*` responses.
`Content-Security-Policy` is deliberately not set at this layer — see
ADR-045. `MAX_REQUEST_BODY_BYTES` is enforced by a raw ASGI middleware
(`app/core/request_size.py`, ADR-046) that rejects oversized requests
with 413 before buffering the body, so Phase E's webhook raw-body HMAC
verification remains unaffected.

`app/trajectory/redaction.py`'s `DEFAULT_SENSITIVE_KEYS` now also covers
`client_secret`/`jwt_secret`/`webhook_secret` (extended in place, not
duplicated) for any future structured-log redaction that reuses it.

### GitHub webhook security and audit logging (Security Phase E)

`POST /api/v1/github/webhook` verifies `X-Hub-Signature-256` (HMAC-
SHA256, constant-time) over the exact raw body bytes before trusting
anything else about the request — see ADR-047. `GitHubWebhookService`
(`app/services/webhook_service.py`) persists a `GitHubWebhookDelivery`
row keyed by GitHub's `X-GitHub-Delivery` id (unique constraint,
SHA-256 payload-hash idempotency/conflict detection — ADR-048) and does
not yet trigger any product pipeline (Phase 12) — this phase only
trusts and records inbound deliveries. The route is unauthenticated by
AgentABI JWT but still rate-limited by client identity and covered by
Phase D's global request-size middleware, which is designed not to
interfere with raw-body signature verification.

`AuditEvent` (`app/models/audit_event.py`) is an append-only security
audit trail — immutable at the database level (migration 0007 blocks
UPDATE and DELETE), tenant-scoped by nullable `organization_id`
(`ON DELETE SET NULL`, never `CASCADE`), redacted metadata via the
existing `app/trajectory/redaction.sanitize()`. `AuditService`
(`app/services/audit_service.py`) is the single append/query surface;
`GET /api/v1/organizations/{organization_id}/audit-events`
(`Permission.AUDIT_READ`, OWNER/ADMIN only) is its read API. See
ADR-049 for the immutability/tenant-scoping/read-authorization design
and the two centralized emission points wired this phase
(`GitHubOAuthService` login events, `AuthorizationService` authorization
denials).

## Security Architecture Overview (consolidated, Security Phase F)

A short summary of Security Phases A–E for anyone evaluating the
system without reading every phase section above.

**Authentication flow.** A user authenticates only via GitHub OAuth2
(`/api/v1/auth/github/login` → GitHub consent → `/api/v1/auth/github/
callback`). The callback exchanges GitHub's code, resolves or creates
an AgentABI `User` from the returned GitHub identity, and issues an
AgentABI-signed HS256 JWT (stdlib-only, ADR-037) — GitHub's own access
token is never persisted (ADR from Phase B). The `state` parameter is
Redis-backed and one-use (ADR-039) to prevent CSRF/replay of the OAuth
flow.

**Authorization flow.** Every protected route depends on
`get_current_user` (validates the JWT: signature, issuer, audience,
expiration, and that the user still exists/is active) and then, for
org/project-scoped routes, `require_organization_permission` /
`require_project_permission` (`app/api/deps/authz.py`). Role is never
trusted from the JWT — it is reloaded from `organization_members` on
every request (ADR-038), so a role downgrade or membership removal
takes effect immediately. `Permission` (`app/authz/permissions.py`)
maps OWNER/ADMIN/MEMBER to allowed actions. A resource in an
organization/project the caller has no membership in returns 404, not
403 (ADR-042), so cross-tenant existence is never leaked; a same-
tenant permission denial returns 403.

**API protection.** All request/response bodies are Pydantic models
(validation + typed serialization — no field is ever exposed that
isn't explicitly on a response model, which is how secrets stay out of
API responses). Mutating routes are rate-limited via fixed-window
Redis counters, fail-closed on Redis failure (ADR-043), keyed by user
id when authenticated else trusted-proxy-aware client IP (ADR-044).
CORS is configured via `Settings`; a standardized JSON error envelope
(`{"error": {"code", "message", "request_id"}}`) is used for every
4xx/5xx (ADR-045); a raw-ASGI request-size limit middleware rejects
oversized bodies with 413 before buffering (ADR-046); standard
security headers are set globally.

**GitHub webhook trust.** `POST /api/v1/github/webhook` is public (no
AgentABI JWT — GitHub can't obtain one) but verifies
`X-Hub-Signature-256` as HMAC-SHA256 over the *raw* request body using
constant-time comparison before trusting anything else (ADR-047).
Each delivery's `X-GitHub-Delivery` id is stored with a unique
constraint plus a SHA-256 payload-hash for idempotency/conflict
detection (ADR-048).

**Audit logging.** `AuditEvent` rows are append-only (a DB trigger
blocks UPDATE/DELETE), tenant-scoped by nullable `organization_id`,
with sensitive metadata redacted through the same sanitizer trajectory
events use. Read access is OWNER/ADMIN only (ADR-049).

**Swagger/OpenAPI.** FastAPI derives the OpenAPI `security` schema
automatically by walking each route's dependency graph — no route
manually declares a security requirement. `HTTPBearer(bearerFormat=
"JWT")` is the one shared scheme (`app/api/deps/auth.py`); Swagger UI's
Authorize button accepts a raw JWT. Public routes (health/ready, OAuth
login/callback, the GitHub webhook) depend on no auth dependency and
so correctly show no security requirement. See `tests/
test_openapi_security.py`.

**Postman.** `postman/AgentABI.postman_collection.json` and
`postman/AgentABI.local.postman_environment.json.example` cover every
implemented route with collection-level Bearer auth and per-request
`noauth` overrides for the public endpoints. See `docs/POSTMAN.md`.

### Security Phase F: Developer/API Tooling + Final Verification

Phase F added no new backend behavior. It made existing security
correctly *visible*: `bearerFormat="JWT"` on the shared `HTTPBearer`
scheme, `summary`/`description` on key routes, a shared
`COMMON_ERROR_RESPONSES` dict (`app/api/v1/errors.py`) documenting the
Phase D error envelope for 400/401/403/404/409/413/422/429/500 via
`include_router(..., responses=...)`, the Postman collection/
environment above, `docs/POSTMAN.md`, this consolidated section, and
`tests/test_openapi_security.py` (asserts the bearer scheme, that
protected/public routes are correctly (un)secured, and that no secret
setting value leaks into the generated schema). See
`docs/SECURITY_VERIFICATION.md` for the final phase-by-phase
verification status.

## Phase 8: LLM Provider Abstraction + OpenAI Integration

Explains deterministic evidence (compatibility changes today; graph/
replay evidence can be wired in later without changing this layer) in
natural language — it never computes evidence. `app/llm/models.py`
defines provider-agnostic, dependency-free dataclasses:
`EvidenceItem` (bounded input), `ExplanationRequest`, and
`ExplanationResponse`. `ExplanationResponse` has no `risk_score`/`pass`/
`warn`/`block`/`compatibility_status`/`final_decision` field — that's a
structural guarantee, not just a prompt instruction (spec §10): there is
no field in the dataclass to put a decision in, so no code path can read
one back out.

`app/llm/provider.py`'s `LLMProvider` is a `Protocol` — the only thing
`ExplanationService` (`app/services/explanation_service.py`) depends on.
`app/providers/openai_provider.py`'s `OpenAIProvider` is the sole
implementation and the *only file in the codebase that imports the
`openai` package* (verified by `tests/test_llm_architectural_invariant.
py`, which walks the AST of every module under `app/`). It uses the
Responses API (`client.responses.create`) with Structured Outputs
(`text.format.type="json_schema"`, `strict=True`) so parsing never
depends on brittle free-form text extraction, and maps every OpenAI SDK
exception (timeout, connection, auth, rate limit, generic) to one of
four domain errors (`LLMProviderTimeout`/`LLMProviderUnavailable`/
`LLMProviderNotConfigured`/`LLMExplanationFailed`/`LLMInvalidResponse`)
without ever including the raw SDK error body or headers, which could
echo the API key.

`ExplanationService.explain_compatibility_changes` bounds the evidence
deterministically first (`app/llm/bounding.py`: max 25 items, clipped
summary/detail text — never the LLM's choice what to drop), builds the
`ExplanationRequest` with an `allowed_reference_ids` set derived from
that bounded evidence, calls the provider, and validates the response's
cited evidence references against that same set *again* — defense in
depth, since `OpenAIProvider` already validates once against its own
request. `app/providers/fake_provider.py`'s `FakeLLMProvider` makes the
whole chain testable with zero network calls or API credits (`success`/
`timeout`/`error`/`invalid_reference` modes).

`POST /api/v1/projects/{project_id}/compatibility/scans/{scan_id}/
explain` is the one exposed endpoint — reuses `Permission.SCAN_EXECUTE`
(the same elevated ADMIN/OWNER-only permission that triggers a scan,
since this calls a paid API) and the existing `scan_replay` Redis
rate-limit bucket, rather than adding a second permission or limiter.

No API key is required for the application to start, for every
deterministic feature to work, or for any test outside the explanation
layer to pass (spec §25) — `OpenAIProvider` raises
`LLMProviderNotConfigured` only when `explain()` is actually called with
no key. Default model is `gpt-4o-mini` (cheap, fast, Structured-Output-
capable — this is bounded text summarization, not a task needing a
frontier reasoning model), overridable via `OPENAI_MODEL`.

Gemini (originally Phase 9) is intentionally not implemented — the
project now targets OpenAI only. The `LLMProvider` Protocol and the
`get_llm_provider` factory (`app/api/deps/llm.py`) are the seam a future
provider would implement; nothing about `ExplanationService` or the API
route would need to change.

Same sandbox restriction as every prior phase: `openai` (like fastapi/
sqlalchemy) isn't installable here. Pure logic (`app/llm/bounding.py`,
the AST-based architectural-invariant test) ran for real — **8/8
passed**. `tests/test_explanation_service.py` (uses only
`FakeLLMProvider`, no OpenAI dependency) and `tests/
test_openai_provider_mock.py` (mocks the `openai` SDK boundary) are
written and `py_compile`-clean but need `pytest-asyncio`, also not
installable here, so they did not execute this session — see
docs/DECISIONS.md.

## Phase 10: Differential Analyzer

Answers "what changed between baseline behavior and candidate
behavior?" — deterministically. `app/differential/` computes this; it
never calls OpenAI or any LLM (`tests/
test_differential_no_llm_dependency.py` proves this by AST inspection,
mirroring Phase 8's architectural-invariant test).

**Input**: two `ReplayRun`s (baseline, candidate), both COMPLETED, both
in the same project — loaded via `ReplayRepository.get_by_id(project_id,
replay_id)`, which is *already* project-scoped, so a cross-project or
cross-org replay id simply doesn't resolve (`ReplayNotFound`) rather
than needing a separate tenant check (spec §23).

**Step alignment** (`app/differential/alignment.py`) is a deterministic
fallback hierarchy, never an LLM: (1) `source_event_id` — a perfect
match when both replays replay the same source trajectory (the common
case: same historical run, different candidate component version); (2)
`sequence_number`, for replays of two different trajectories; (3)
`component_identity`, first-available pairing in ascending sequence
order; (4) whatever's left becomes `STEP_ADDED`/`STEP_REMOVED`. Every
pair records which rule matched it.

**Comparison** (`app/differential/analyzer.py`, `app/differential/
value_diff.py`): per aligned step pair, detects `STEP_STATUS_CHANGED`,
`TOOL_CHANGED` (component/version), `PROVIDER_INVOCATION_CHANGED`
(replay `kind` changed), `INPUT_CHANGED`/`OUTPUT_CHANGED` via a pure
recursive dict/list/scalar diff (sorted-key iteration for deterministic
ordering; missing-vs-null stays distinguishable via key-presence
checks, never `.get() is not None`), `ERROR_INTRODUCED`/
`ERROR_RESOLVED`/`ERROR_CHANGED` (sanitized category only, never a raw
stack trace), and `LATENCY_CHANGED` (only when both sides have a real
measured `duration_ms` — never fabricated, no regression-threshold
judgment, that's Phase 11's job). Sensitive fields (reusing
`app.trajectory.redaction`'s key set) are compared on their *raw* value
to correctly detect a change, but only ever recorded redacted.

**Output**: `DifferentialReport` (pure dataclass) — deterministic
summary metrics (`matched_steps`/`added_steps`/`removed_steps`/
`new_failures`/etc., spec §15) and zero risk/decision field, same
structural discipline as Phase 8's `ExplanationResponse`.

**Persistence**: `DifferentialReportRecord`/`DifferentialChangeRecord`
(migration 0008) — immutable once created (UPDATE-blocking trigger,
mirrors `replay_steps`), idempotent per `(project_id,
baseline_replay_id, candidate_replay_id, analyzer_version)` unique
constraint (spec §19 — a retry returns the existing report, never a
duplicate), `analyzer_version="1"` frozen at compute time so a future
rule change never silently reinterprets an old report (spec §20), and a
canonical SHA-256 `content_hash` (reusing `app.domain.checksums`) for
reproducibility.

**API**: `POST/GET /api/v1/projects/{project_id}/differential/reports`,
`GET .../reports/{report_id}` — `DIFFERENTIAL_EXECUTE` (ADMIN/OWNER,
same cost class as `SCAN_EXECUTE`/`REPLAY_EXECUTE`, reuses the existing
`scan_replay` rate-limit bucket) and `DIFFERENTIAL_READ` (any
membership) added centrally to `app/authz/permissions.py`, never as a
scattered role check.

Phase 11 (risk scoring) and Phase 8 (LLM explanation) both consume a
`DifferentialReportRecord` as an input; this phase never invokes either.

Same sandbox restriction as every prior phase. Pure logic ran for
real via `pytest --noconftest`: value-diff, alignment, the full
analyzer, and the no-LLM-dependency structural test — **45/45 passed**.
Fixing this phase's `app/authz/permissions.py` addition also required
updating `tests/test_authz_permissions.py`'s hardcoded expected sets
(a genuine regression, caught and fixed this session, not left for
later). Full regression sweep across all pure-runnable tests: **290
passed** (up from the prior phase's count), no new failures beyond the
pre-existing async/FastAPI-dependent ones every phase already
documents. `tests/test_differential_service.py` (real-Postgres
integration, spec §29) is written and `py_compile`-clean but needs
SQLAlchemy, not installed here — not executed.
