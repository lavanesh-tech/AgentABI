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

## Phase 11: Deterministic Risk Engine

Answers "given all deterministic evidence, should this change PASS,
WARN, or BLOCK?" — never with an LLM. `app/risk/` (models, rules,
engine) is pure stdlib `dataclasses`/`enum.StrEnum`, has no SQLAlchemy/
FastAPI/OpenAI import, and is proven so by AST inspection: "risk" was
added to `tests/test_llm_architectural_invariant.py`'s
`DETERMINISTIC_PACKAGES` tuple (alongside a new "differential" entry,
reinforcing Phase 10's own boundary) rather than duplicating a second
structural-test file. The engine works with `OPENAI_API_KEY=` unset —
it never reads it, never calls out, and never receives OpenAI output as
an input.

**RiskContext** (`app/risk/models.py`) is the only input `app.risk.
engine.evaluate()` ever sees: a typed, frozen dataclass of already-
computed deterministic evidence (compatibility scan summary/severity
counts, differential summary/step-difference flags, best-effort blast-
radius total). `app/services/risk_service.py` is the only place one is
constructed, from `CompatibilityScan`/`DifferentialReportRecord` ORM
rows and `BlastRadiusService.compute()` — never from `app.llm` output.

**Rules** (`app/risk/rules.py`) — 8 named score rules plus 2 hard-block
rules, each a pure `RiskContext -> TriggeredRule | None` function,
centrally discoverable via the `SCORE_RULES`/`HARD_BLOCK_RULES` tuples:

| rule_id | category | delta | trigger |
|---|---|---|---|
| `COMPAT_BREAKING_CHANGE` | compatibility | 30 | scan status `breaking` or any breaking change |
| `NEW_REPLAY_FAILURE` | replay | `min(15×new_failures, 45)` | differential `new_failures > 0` |
| `REMOVED_REQUIRED_STEP` | differential | 20 | `STEP_REMOVED` on a baseline step that wasn't already failed/skipped |
| `HIGH_BLAST_RADIUS` | blast_radius | 10 (3-9 affected) / 20 (≥10 affected) | `BlastRadiusResult.total_affected` |
| `OUTPUT_SCHEMA_BREAK` | differential | 20 | differential `schema_changes > 0` |
| `TOOL_INVOCATION_CHANGED` | differential | 10 | any `TOOL_CHANGED`/`PROVIDER_INVOCATION_CHANGED` |
| `ERROR_INTRODUCED` | differential | 15 | any `ERROR_INTRODUCED` |
| `SIGNIFICANT_LATENCY_INCREASE` | latency | 10 | max measured `latency_percent_delta ≥ 50%` |

`resolved_failures`/step-added evidence has deliberately no rule keyed
on it — spec §11's "failure resolved must NOT increase risk" holds
because there is nothing to increase it, not a special-cased subtraction.

**Double-counting policy** (spec §16): each category (`compatibility`,
`replay`, `differential`, `blast_radius`, `latency`) has a fixed cap —
40/45/50/20/15 — applied to that category's *summed raw deltas* before
adding to the overall score, which is then capped at 100. Several
DIFFERENTIAL-category rules firing on the same underlying differential
report (e.g. `OUTPUT_SCHEMA_BREAK` + `TOOL_INVOCATION_CHANGED` +
`ERROR_INTRODUCED` + `REMOVED_REQUIRED_STEP`) is legitimate — it's real,
distinct evidence — but their combined contribution is capped rather
than left to sum unbounded.

**Score and decision**: `score` is 0-100; `RISK_ENGINE_VERSION = "1"`.
Banding: **PASS < 30, WARN 30-69, BLOCK ≥ 70** (the spec's recommended
thresholds, adopted as-is). **Hard-block rules** (`HARD_BLOCK_CRITICAL_
COMPAT_BREAK` on any CRITICAL-severity compatibility change,
`HARD_BLOCK_NEW_REPLAY_FAILURE` on any new replay failure) force
`decision = BLOCK` independent of the numeric score — a hard-blocked
assessment still reports the score the rules alone would have produced
(never inflated by the hard-block rule itself, which always carries
`score_delta = 0`) so a reviewer can see how close the deterministic
signals were on their own. A `RiskContext()` with no evidence at all
triggers nothing: `score=0, decision=PASS, hard_block=False` — there is
no special-cased "no evidence" branch, it falls out of every rule's
predicate not matching.

**Reasons/provenance** (spec §19-§20): every triggered rule carries
`rule_id`, `category`, a human-readable `description`, its raw
`score_delta`, and `evidence_refs` — stable string pointers (e.g.
`"compatibility_scan:<id>"`, `"differential.summary.new_failures"`)
into real evidence the engine was given, never invented identifiers.

**Persistence**: `RiskAssessmentRecord`/`RiskRuleResultRecord`
(migration 0009) — same immutable-evidence pattern as `differential_
reports`/`differential_changes` (UPDATE-blocking trigger), idempotent
per `(project_id, compatibility_scan_id, differential_report_id,
risk_engine_version)` unique constraint, and a canonical SHA-256
`content_hash` over the assessment's deterministic content (reusing
`app.domain.checksums`) supporting the reproducibility test.

**Blast radius** is best-effort: `RiskService._compute_blast_radius`
catches `GraphUnavailable`/`GraphComponentNotFound` and returns `None`
("not computed" — no signal) rather than coercing to `0` ("computed,
nothing affected"), which would be a fabricated finding.

**API**: `POST/GET /api/v1/projects/{project_id}/risk/assessments`,
`GET .../assessments/{assessment_id}` — `RISK_EXECUTE` (ADMIN/OWNER,
reuses the `scan_replay` rate-limit bucket, same cost class as
`DIFFERENTIAL_EXECUTE`) and `RISK_READ` (any membership) added
centrally to `app/authz/permissions.py`; `tests/
test_authz_permissions.py`'s hardcoded expected sets were updated in
the *same* change (learned from Phase 10's regression) rather than
discovered afterward.

**Phase 12 contract**: `decision` (`PASS`/`WARN`/`BLOCK`), `score`,
`hard_block`, and `rule_results[]` are exactly the fields a GitHub
check-run status needs — Phase 11 makes no GitHub API call itself.

**Phase 8 integration**: `app/llm/` is unchanged this phase — no new
field was added to `ExplanationRequest`. OpenAI may explain an
already-computed `RiskAssessment` only on an explicit, separate call;
`RiskService` never invokes `app.llm`/`ExplanationService` itself.

**Verification**: pure logic ran for real via `pytest --noconftest` —
`tests/test_risk_rules.py` (rule-level, incl. no-evidence, threshold
bands, hard-block, evidence-ref presence) and `tests/test_risk_engine.
py` (exact decision-boundary values 29/30/69/70/100 via `_decide`
directly, reproducibility, score-cap-at-100, double-counting-cap,
deterministic rule ordering, resolved-failures-don't-increase-score) —
**26/26 passed**. Full regression sweep: **313 passed**, no new
failures beyond the pre-existing async/FastAPI-dependent ones every
phase already documents (confirmed `tests/test_authz_permissions.py`
still 12/12 green after the new permissions). `tests/
test_risk_service.py` (real-Postgres integration, spec §37) is written
and `py_compile`-clean but needs SQLAlchemy, not installed here — not
executed; no dedicated `test_risk_api.py` was added, following Phase
10's own precedent of relying on service-level tests plus the
centralized-permission unit tests where FastAPI/httpx aren't
executable in this sandbox.

## Phase 12: GitHub PR / Release Integration

**Flow**: GitHub `pull_request` webhook (`opened`/`synchronize`/
`reopened` only — every other action is safely ignored, not an error)
-> Security Phase E's existing HMAC/idempotency/rate-limit validation in
`GitHubWebhookService.process()` (unchanged) -> a new additive dispatch
step in the webhook route (`app/api/v1/github_webhook.py`) resolves the
PR event and, only for a newly-accepted `pull_request` delivery, invokes
`GitHubPullRequestAnalysisService.analyze_pull_request` -> Phase 5
`CompatibilityService.run_scan` -> Phase 11 `RiskService.run_assessment`
-> `decision_to_conclusion` -> a GitHub check run published via the
`GitHubChecksClient` Protocol. GitHub receives only the already-computed
deterministic PASS/WARN/BLOCK result; nothing in this phase computes
compatibility, differential, or risk itself — see ADR-059 for why
Replay/Differential are deliberately not wired into this pipeline yet.

**Repository mapping**: `GitHubRepositoryMapping` (migration 0010) keys
a GitHub repository to an AgentABI project by GitHub's immutable numeric
`github_repository_id` (never `owner/repo`, which changes on rename/
transfer). It also carries the explicit analysis contract (ADR-060):
`component_id` (required to start analysis) and an optional
`baseline_version` (defaults to the component's latest registered
`ComponentVersion`). Managed via `POST/GET/DELETE /api/v1/projects/
{project_id}/github/repositories[/{mapping_id}]`
(`app/api/v1/github_repositories.py`), gated by two new centralized
permissions, `GITHUB_INTEGRATION_READ` (any membership) and
`GITHUB_INTEGRATION_MANAGE` (ADMIN/OWNER) — never a scattered ad-hoc
role check.

**Exact-SHA pinning (stale-result protection, spec §25)**: every
`GitHubPullRequestAnalysis` row (migration 0010) is created with, and
permanently pinned to, the exact `head_sha` of the commit it analyzes —
never reassigned. Every check-run create/update call always uses
`analysis.head_sha`, never a "latest" or externally-passed current
value, so an older commit's analysis completing after a newer commit's
analysis can never overwrite or be confused with the newer commit's
check (GitHub's Checks API itself associates a check run with the exact
SHA given at creation). A `synchronize` event with a new `head_sha`
always produces a new logical analysis row; historical rows remain
auditable, never deleted or overwritten. Idempotency key: `(github_
repository_id, pull_request_number, head_sha, analysis_version)` — a
database unique constraint, checked before any pipeline work begins, so
a redelivered webhook for an already-analyzed commit reuses the
existing row rather than recomputing or republishing.

**Check conclusion mapping**: centralized and exhaustively tested in
`app/github/check_mapping.py` — `decision_to_conclusion` is a total
function over every `RiskDecision` member (PASS->success, WARN->neutral,
BLOCK->failure); the LLM never chooses a conclusion (spec §12). The
check body (`build_completed_output`) is concise markdown — decision,
score, engine version, hard-block flag, up to 5 top triggered rules,
compatibility summary, never a raw JSON evidence dump. WARN's summary
explicitly states "AgentABI decision: WARN" and is textually distinct
from PASS's; PASS's summary never claims zero risk, only that no
configured threshold was exceeded; BLOCK's summary states the score and
whether a hard-block rule fired. An optional Phase 8 OpenAI explanation
may be appended verbatim as its own section — it never influences
`decision`/`score` and is never required to publish a check.

**Credential boundary**: see ADR-058. `GitHubCredentialProvider` is a
separate Protocol from Phase B's OAuth login flow — a user's OAuth
access token is never reused as a permanent integration credential.
`HttpxGitHubChecksClient` never logs an Authorization header, access
token, or webhook secret; a `GitHubAPIUnavailable`/`GitHubAuthentication
Failed`/`GitHubCheckPublishFailed` error carries only a sanitized
message.

**Failure isolation (spec §28)**: deterministic evidence is committed to
the database *before* any GitHub publish attempt — `RiskAssessmentRecord`
is never recomputed or mutated because a check-run publish failed. A
publish failure sets `GitHubPullRequestAnalysis.status =
PUBLISH_FAILED` with a sanitized `publish_error`, safely retryable
later, never silently reported as success.

**Persistence**: `GitHubPullRequestAnalysis` (migration 0010) is
deliberately *not* immutable-once-created, unlike `differential_reports`/
`risk_assessments` — see ADR-061. Audit actions `GITHUB_PR_ANALYSIS_
STARTED`/`GITHUB_PR_ANALYSIS_COMPLETED`/`GITHUB_CHECK_PUBLISHED`/
`GITHUB_CHECK_FAILED` are recorded with only safe identifiers (project
id, repository id, PR number, head SHA, risk assessment id, decision) —
never a token.

**Route wiring**: see ADR-062 — the PR-analysis dispatch lives outside
`GitHubWebhookService.process()`, additive and exception-isolated, so
every already-passing Security Phase E webhook test stays at zero
regression risk.

**Verification**: pure logic ran for real via `pytest --noconftest` —
`tests/test_github_check_mapping.py` (conclusion-mapping exhaustiveness,
PASS/WARN/BLOCK summary content and distinctness, top-rules truncation)
and `tests/test_github_pr_webhook_models.py` (supported/unsupported
actions, malformed/missing-field payloads, the new `tests/fixtures/
github_pull_request_opened.json` sample fixture) — **28/28 passed**.
Full regression sweep: **341 passed**, no new failures beyond the
pre-existing async/FastAPI-dependent gaps every phase already documents
(confirmed `tests/test_authz_permissions.py` still 12/12 green after the
two new GitHub permissions). `tests/test_github_checks_client_fake.py`
(async, `FakeGitHubChecksClient`-based) and `tests/
test_github_pr_analysis_service.py` (real-Postgres integration,
including the mandatory stale-SHA test, spec §25/§37) are written and
`py_compile`-clean but need `pytest-asyncio`/SQLAlchemy, not installed
here — not executed; no dedicated `test_github_repository_mapping_api.
py` was added, following Phase 10/11's own precedent of relying on
service-level tests plus the centralized-permission unit tests where
FastAPI/httpx aren't executable in this sandbox. `ruff format --check`/
`ruff check` clean; `python3.12 -m py_compile` clean across `app`/
`tests`/`alembic`; `mypy` unavailable (`No module named mypy`), same as
every phase. No real GitHub credentials exist in this environment, so no
live GitHub Checks API smoke test was performed — honestly skipped, not
fabricated.

## Phase 13: Kafka Event Pipeline

**Purpose**: decouple event ingestion (the GitHub webhook request) from
analysis execution (the deterministic pipeline) without moving any
business logic into Kafka producers/consumers. Kafka is transport/
orchestration infrastructure only — `app/risk/`, `app/compatibility/`,
`app/differential/` are all completely untouched this phase.

**Flow**: `github_webhook` route -> `GitHubPullRequestAnalysisService.
start_analysis` (validates the mapping, persists a PENDING `GitHubPull
RequestAnalysis` row — cheap enough for the request thread) -> `app/
events/analysis_events.build_analysis_requested_event` -> `EventPublisher.
publish` -> topic `agentabi.analysis.requests` -> `app.kafka.worker`'s
`KafkaEventConsumer` -> `AnalysisRequestHandler` -> `GitHubPullRequest
AnalysisService.run_analysis` (the actual Phase 5 compatibility -> Phase
11 risk -> GitHub check-publish pipeline, unchanged from Phase 12) ->
optionally `github.pr.analysis.completed`/`.failed` on
`agentabi.analysis.results`.

**Event envelope** (`app/events/envelope.py`, pure — no SQLAlchemy/
FastAPI/aiokafka import): `event_id` (UUID4), `event_type`,
`event_version` (int, explicit per type in `SUPPORTED_EVENT_VERSIONS`),
`occurred_at` (ISO 8601), `correlation_id`, `project_id`/
`organization_id`, a typed `payload` dict, and `metadata` (transport-
only — the partition key lives here, never in `payload`). Serialization
is deterministic stdlib `json` with `sort_keys=True` (ADR-068, not the
already-declared-but-uninstallable-here `orjson`). `validate_event_
version` rejects any version other than the one currently registered
for that `event_type` — never a silent reinterpretation (spec §6).

**Event taxonomy** (`app/events/analysis_events.py`): exactly three
types — `github.pr.analysis.requested`, `.completed`, `.failed` — each
with a typed payload dataclass built from plain scalars extracted from
ORM rows, never an ORM object itself. Completed/failed payloads carry
only identifiers (`risk_assessment_id`, `decision`, `score`; or a safe
`error_category` + `retry_count`) — never the raw rule-results/
compatibility-diff evidence or an exception message/stack trace (spec
§27/§28/§45).

**Topics and partitioning**: two topics by direction (`agentabi.
analysis.requests`/`agentabi.analysis.results`) plus one DLQ topic
(`agentabi.analysis.dlq`) — see ADR-067. Partition key is
`f"{github_repository_id}:{pull_request_number}"` (ADR-066) — a
convenience for same-PR ordering, never the actual correctness
mechanism (see exact-SHA below).

**Producer/consumer abstraction**: `app/events/publisher.EventPublisher`
(Protocol, `async def publish(self, event) -> None`) and `app/events/
handler.EventHandler` (Protocol, `async def handle(self, event) -> None`)
— application/service code depends on these, never on `aiokafka`
directly (spec §8/§9). `KafkaEventPublisher`/`KafkaEventConsumer` (`app/
events/kafka_publisher.py`, `app/kafka/consumer.py`) are the production
implementations; `InMemoryEventPublisher` (`app/events/fake_publisher.
py`) is the test double, in the production tree since more than one test
module needs it (mirrors `app.github.checks_fake.FakeGitHubChecksClient`).

**KAFKA_ENABLED optionality**: `Settings.kafka_enabled` defaults to
`false` everywhere (ADR-063). `false` — `github_webhook`'s dispatch step
calls `GitHubPullRequestAnalysisService.analyze_pull_request` exactly as
Phase 12 always did (internally, `start_analysis` immediately followed
by `run_analysis` — ADR-064, no duplicated pipeline implementation).
`true` — the route calls `start_analysis`, publishes the request event,
and returns; the worker performs `run_analysis` later. `aiokafka` is
imported lazily (function-scope, not module-scope) in `app/events/
factory.py` and `app/core/readiness.py`, so a process that never enables
Kafka never needs it importable at all — app startup/shutdown and
`/ready` all stay fully functional with Kafka disabled.

**Exact-SHA invariant carries over from Phase 12, strengthened
structurally**: `run_analysis` takes an `expected_head_sha` and compares
it against the persisted, immutable `GitHubPullRequestAnalysis.head_sha`
before doing any work, raising `GitHubAnalysisHeadShaMismatch` on a
mismatch (spec §16/§38). Since a row's `head_sha` is never reassigned,
and every check-publish call is keyed off `analysis.head_sha` (never a
"latest" value), this makes the stale-result protection hold regardless
of Kafka delivery order — see ADR-066's note that partition-key ordering
is a convenience, not the safety mechanism.

**Idempotency under at-least-once delivery** (ADR-065): no new dedup
table — `run_analysis` branches on the persisted `status`: COMPLETED is
a no-op on redelivery, FAILED is not auto-retried (spec §20), and
PUBLISH_FAILED retries the check publish only, reusing the existing
`risk_assessment_id`/`compatibility_scan_id` rather than recomputing
(spec §28's "never recompute risk solely because publishing failed").

**Consumer offset/retry/DLQ policy** (`app/kafka/consumer.py`):
`enable_auto_commit=False` — commit only after the handler completes
successfully (spec §19). One message at a time, no unlimited concurrent
tasks (spec §26). `TransientEventProcessingError` (e.g. `GitHubAPI
Unavailable`) is retried up to 3 times in-process before routing to the
DLQ topic; `PermanentEventProcessingError` (malformed payload,
unsupported version, a permanent domain error) is never retried — routed
to DLQ immediately (spec §20/§21/§22). A poison message (invalid JSON,
missing required fields) is caught at `deserialize_envelope`, logged
with safe metadata only, sent to DLQ, and the loop continues — it can
never crash the consumer.

**Security** (spec §29/§30/§43): structured log fields are limited to
event id/type/topic/partition/offset/correlation id/project id/retry
count/duration — never a token, webhook secret, or the full payload.
`tests/test_events_analysis_events.py::test_no_secret_fields_in_any_
event_schema` asserts none of the three event payloads can ever contain
a token/secret/authorization/api_key/password/jwt substring.

**Worker entrypoint**: `python -m app.kafka.worker` (also `make
worker`) — opens one short-lived Postgres session per consumed message
(mirrors `get_db_session`'s per-request lifecycle), never a long-lived
shared session across events (spec §46's crash-and-redeliver recovery
property).

**Readiness**: `/ready`'s new `kafka` check (`app/core/readiness.
check_kafka_connection`) returns `True` immediately when `KAFKA_ENABLED=
false` (spec §31 — "not applicable," never "failing"); when enabled, it
starts the producer (idempotent) and reports success/failure.

**Local Docker Compose**: unchanged — the existing Phase 1 `kafka`
service (KRaft mode) is reused as-is; topics rely on Kafka's default
auto-create behavior (ADR-067), no explicit topic-init step added this
phase.

**Verification**: pure logic ran for real via `pytest --noconftest` —
`tests/test_events_envelope.py` (UUID/version/ISO-timestamp assignment,
deterministic serialization, round-trip, malformed/missing-field
rejection, version validation) and `tests/test_events_analysis_events.
py` (partition-key stability, all three event builders' payload shape,
the no-secrets assertion, request-payload round-trip/parsing) —
**28/28 passed**. Full regression sweep: **369 passed** (up from Phase
12's 341), no new failures beyond the pre-existing async/FastAPI-
dependent gaps every phase already documents (the new `tests/
test_events_fake_publisher.py` adds 5 more async-only failures to that
same documented category — `pytest-asyncio` still unavailable).
`ruff format --check`/`ruff check` clean; `python3.12 -m py_compile`
clean across `app`/`tests`/`alembic`; `mypy` unavailable, same as every
phase. `tests/test_events_fake_publisher.py`, `tests/test_kafka_
analysis_handler.py` (real-Postgres integration, incl. duplicate-event
idempotency), and `tests/test_github_pr_analysis_service.py`'s new
Phase 13 tests (`start_analysis`/`run_analysis` split, head_sha-mismatch
rejection, redelivery idempotency, PUBLISH_FAILED retry-without-
recompute) are written/`py_compile`-clean, not pytest-executed (need
`pytest-asyncio`/SQLAlchemy). `app/kafka/consumer.py` and `app/events/
kafka_publisher.py` (both `aiokafka`-dependent) are written/`py_compile`-
clean only — no dedicated consumer unit test was added given the
sandbox can't import `aiokafka` at all, so a test constructing one would
assert nothing beyond what code review already covers; its retry/DLQ/
poison-message logic is documented above and exercised indirectly
through `AnalysisRequestHandler`'s tests, which cover the actual
domain-error classification the consumer dispatches on. No live Kafka
broker exists in this environment — the optional real-Kafka smoke test
(spec §41) was honestly skipped, never fabricated.

## Phase 14: Frontend Dashboard

**Purpose**: a production-quality recruiter/demo frontend answering
"what changed, what depends on it, what behavior changed, what is the
deployment risk, and why" — never a generic admin CRUD UI, never a
chatbot. Built entirely against the backend surface inventoried at the
start of this phase (spec §1); the one confirmed gap (PR-analysis
history had no read endpoint) was closed with the minimum necessary
addition — see ADR-069 — rather than any broader backend redesign.

**Stack**: Next.js 14 (App Router), React 18, TypeScript (strict, no
`any`), Tailwind CSS, TanStack Query, React Flow (dependency graph),
Recharts (declared, lightly used — most "visualization" here is
structured tables/badges over deterministic evidence, deliberately not
chart-heavy, per spec §5's information-density guidance over decoration).

**Structure** (`frontend/`, independently runnable, never mixed into
the FastAPI package):
- `app/` — routes. `(protected)/` is a route group wrapping every
  authenticated screen in `ProtectedShell` (sidebar + header + redirect-
  to-`/login` when unauthenticated); `login/` and `auth/callback/` are
  the only public routes.
- `lib/api-client.ts` — the single fetch boundary. Reads
  `NEXT_PUBLIC_AGENTABI_API_URL`, attaches the bearer token from
  `lib/auth-storage.ts`, parses the standardized `{error: {code,
  message, request_id, fields?}}` envelope into a typed `ApiError`,
  and fires a registered 401 handler (wired by `AuthProvider`) that
  clears the session — no route component touches `fetch` directly.
- `features/*/hooks.ts` — one TanStack Query hook module per
  implemented backend resource (projects, components, compatibility,
  graph, trajectories, replays, differential, risk, github, audit),
  each mutation invalidating exactly the query keys it affects.
- `lib/permissions.ts` — a frontend mirror of `app/authz/
  permissions.py`'s MEMBER/ADMIN/OWNER -> permission map. UX only
  (hides/disables controls); the backend remains the sole
  authorization authority, exactly as spec §29 requires.
- `types/api.ts` — hand-written types matching the inventoried Pydantic
  response schemas field-for-field; nothing invented.
- `components/diff/StructuredDiffTable.tsx` — the one reusable
  Change Type / Path / Before / After / Severity / Evidence view (spec
  §15), shared by the Compatibility and Differential screens; raw JSON
  is an expandable secondary view, never the primary display.
- `components/risk/*` — `RiskDecisionBadge`, `RiskScoreBar` (renders
  the configured PASS 0-29 / WARN 30-69 / BLOCK 70-100 thresholds and
  flags when a hard-block rule forced the decision independent of
  score), `RiskRuleList` (per-rule id/description/score-delta/
  evidence-refs/hard-block).
- `components/graph/DependencyGraph.tsx` — React Flow rendering of real
  `GET .../graph/dependents` + `GET .../graph/blast-radius` data;
  changed/direct/transitive/unaffected tiers come entirely from the
  blast-radius response, never computed in the browser.

**Auth flow** (see ADR-070 for the full rationale): GitHub OAuth stays
entirely backend-owned (`GET /auth/github/login`,
`GET /auth/github/callback`) with zero code changes; only
`github_oauth_redirect_uri` is configured to point at this app's own
`/auth/callback` route instead of the backend's. That route forwards
GitHub's `code`/`state` to the backend callback via an unauthenticated
client fetch, stores the returned JWT in `sessionStorage`, and redirects
into the app. Logout is client-side token clearing only — the backend
has no logout route (stateless JWT).

**Verification**: same sandbox network restriction as every backend
phase now also blocks `npm install` (`403 Forbidden` from the npm
registry) — `npm run lint`/`typecheck`/`test`/`build` and Playwright
could not be executed. All frontend source is written, type-annotated
by hand against the inventoried backend contract, and reviewed, but
not machine-verified beyond that. `docker compose config` validates the
added `web` service cleanly; `docker build ./frontend` could not run
(daemon not running in this sandbox). See docs/ROADMAP.md's Phase 14
detail section for the exact commands to run locally to complete
verification.

## Phase 15: OpenTelemetry Distributed Tracing

**Purpose**: trace one request/event across every hop — `GitHub Webhook
-> FastAPI -> Kafka Producer -> Kafka -> Worker -> Compatibility/Replay/
Differential/Risk -> Postgres/Neo4j/Redis -> GitHub API -> optional
OpenAI explanation` — as pure observability. Tracing never influences
PASS/WARN/BLOCK, compatibility classification, blast radius, or any
other deterministic result (spec §2/§41); every span helper is designed
so removing it changes nothing but what's exported.

**Central module** (`app/observability/`, the only place that touches
`opentelemetry.*`):
- `tracing.py` — `setup_tracing(settings)` (idempotent, process-wide,
  no-op unless `OTEL_ENABLED=true` and the SDK is importable),
  `shutdown_tracing()`, `start_span(name, attributes=, kind=,
  parent_context=)` (the one span-creation helper every other module
  uses — degrades to a no-op contextmanager yielding `None`),
  `set_current_span_attributes(...)`, `current_trace_context()` (for
  log enrichment), `instrument_fastapi_app`/`instrument_httpx`/
  `instrument_sqlalchemy`.
- `propagation.py` — `inject_trace_headers()`/`extract_trace_context()`,
  W3C `traceparent`/`tracestate` as Kafka header tuples
  (`list[tuple[str, bytes]]`). Pure, no-op when OTel is unavailable.
- `redaction.py` — `safe_attributes()`, the single redaction boundary
  every span attribute passes through: drops any key matching a broad
  substring blocklist (`authorization`, `*token*`, `*secret*`,
  `*password*`, `*api_key*`, `cookie`, `jwt`, ...) entirely (no
  placeholder value), truncates long strings, and stringifies non-
  primitive values rather than attaching them raw.

**Config** (`Settings`, all prefixed `otel_`): `otel_enabled` (default
`False`), `otel_service_name` (`agentabi-api` default; the worker
overrides to `agentabi-worker` at `setup_tracing()` call time via
`settings.model_copy(update=...)`), `otel_service_version`,
`otel_exporter_otlp_endpoint`, `otel_exporter_otlp_protocol`,
`otel_traces_sampler` (`always_on`/`always_off`/
`parentbased_traceidratio`, default the latter), `otel_traces_sampler_arg`
(default `1.0` — local-dev "trace everything"; production sets a lower
ratio via env, never hardcoded), `otel_environment` (falls back to
`environment` via `otel_resource_environment`).

**Correlation ID vs trace ID**: `X-Correlation-ID` (spec §8, unchanged
from Security Phase D) remains the request-identity mechanism used by
`app/api/v1/errors.py` and audit logging; trace/span IDs are a separate,
additive concern. `app/core/logging.py`'s new `_add_trace_context`
processor adds `trace_id`/`span_id` to every log line emitted inside an
active span, alongside — never replacing — `correlation_id`.

**Kafka propagation (mandatory, spec §10)**: `KafkaEventPublisher.publish`
calls `inject_trace_headers()` and passes the result as `send_and_wait`'s
`headers=` kwarg; `KafkaEventConsumer._process_one` calls
`extract_trace_context(message.headers)` and passes the resulting
context as `start_span`'s `parent_context`, so the consumer span is a
child of the producer's span. `EventEnvelope`'s field set is completely
unchanged — trace context never enters the payload or `metadata` dict.
`tests/test_kafka_trace_regression.py` asserts this structurally.

**Domain spans** (`agentabi.compatibility.analyze`,
`agentabi.replay.execute`, `agentabi.differential.analyze`,
`agentabi.risk.evaluate`, `agentabi.github.pr_analysis`): each service's
public entrypoint now wraps a renamed `_*_impl` method in `start_span`,
rather than importing `app.observability` into `app/risk/`'s pure
engine (spec §15 — kept exactly as isolated as `tests/
test_risk_architectural_invariant.py` already enforces).

**Outbound HTTP / DB / graph / cache**: `instrument_httpx()` (global
`HTTPXClientInstrumentor`, covers the GitHub checks client, GitHub OAuth
client, and OpenAI's httpx-backed SDK with zero per-call-site changes)
and `instrument_sqlalchemy()` (bound to the async engine in `app/core/
database.py`, no bind-parameter capture) are auto-instrumentation;
`github.check.create`/`.update` and `github.oauth.exchange` are also
manually named (auto-instrumentation alone doesn't give them AgentABI-
specific semantics). Neo4j has no mature stable OTel instrumentation
this phase relies on, so `Neo4jGraphRepository._run` — the single
Cypher-execution boundary every repository method already funnels
through — gets one manual `neo4j.query` span per call, tagged only with
the query's leading clause keyword (`MERGE`/`MATCH`/...), never full
Cypher text or bound params. Redis similarly gets manual boundary spans
(`redis.rate_limit.check`, `redis.oauth_state.save`/`.consume`) with no
rate-limit key or OAuth state value ever attached.

**Failure-open** (spec §24/§28): every SDK/exporter construction path in
`setup_tracing`/`instrument_*` catches all exceptions and logs a
warning rather than raising; a down collector, bad endpoint, or missing
package never fails startup, webhook processing, Kafka processing, or
readiness. `GET /api/v1/ready` has no telemetry dependency.

**Local collector**: `docker-compose.yml`'s `otel-collector` service
(`otel/opentelemetry-collector-contrib`, `observability/otel-collector-
config.yaml` — OTLP receiver on 4317/4318, stdout `debug` exporter, no
credentials, no cloud exporter). The `api` service is never
`depends_on` it. OTLP is the sole exporter boundary — AgentABI is never
coupled to a specific tracing backend; point the collector's config at
Jaeger/Tempo/a vendor endpoint later without touching application code.

**Verification**: `opentelemetry-*` are pure-Python wheels but, like
every other dependency in this project, could not be installed in this
sandbox this session (`pip install opentelemetry-api` — "No matching
distribution found", PyPI itself unreachable). All observability code
is written, `ruff format --check`/`ruff check`/`python3.12 -m
py_compile` clean; new tests are written/`py_compile`-clean, not
pytest-executed (no project dependency, including `pytest` itself, is
installed this session). `docker compose config` validates the added
service. No real trace smoke test was produced — both a working install
and a running collector are required and neither is available here.

## Phase 16: Prometheus Metrics + Grafana Dashboards

**Purpose**: answer "is AgentABI healthy right now" from a scrape
endpoint — request rate/error rate/latency, analysis throughput, Kafka
throughput/failures, PASS/WARN/BLOCK counts, GitHub/OpenAI call health —
as pure observability. Metrics never compute or alter compatibility
results, replay outcomes, differential reports, risk scores, or PASS/
WARN/BLOCK; they only observe values the deterministic engines already
produced (spec §2, unchanged from every prior phase's invariant).

**Deliberately separate from tracing** (ADR-073): `app.observability.
tracing` (Phase 15) is the only module touching `opentelemetry.*`;
`app.observability.metrics` (Phase 16) is the only module touching
`prometheus_client`, never routed through OTel's metrics API. Both share
one package (`app/observability/`), one `__init__.py` re-export surface,
and one defensive posture — library absent, or `*_ENABLED=false` ->
complete no-op; any internal failure -> logged and swallowed, never a
request-breaking exception.

**Central module** (`app/observability/metrics.py`): `_counter`/
`_histogram`/`_gauge` factory functions build real `prometheus_client`
objects when the library is importable, or a `_NoOpMetric` stand-in
(same `.labels().inc()/.observe()/.set()` call shape) otherwise — every
other module records through small `record_*()`/`track_*_in_progress()`
helpers, never touching `prometheus_client` directly. A single
process-wide `CollectorRegistry` backs every metric (`_get_registry()`),
rendered by `render_metrics(settings)` for the `/metrics` route.

**Cardinality safety (mandatory, spec §22; ADR-074)**: `_assert_safe_
labels()` runs at metric-registration time (import time) against
`FORBIDDEN_LABEL_NAMES` — `project_id, organization_id, component_id,
event_id, trace_id, request_id, correlation_id, pull_request_number,
head_sha, email, github_username, url, exception, exception_message` —
raising `ValueError` if any declared labelname matches. `tests/
test_metrics_cardinality_safety.py` re-verifies the same set statically
via AST inspection of every `_counter`/`_histogram`/`_gauge` call in the
module, independent of the runtime check. HTTP request labels use the
Starlette route *template* (`request.scope["route"].path`), never the
resolved path — an unmatched/probed route collapses to one bounded
`"unmatched"` label rather than an unbounded raw path.

**Config** (`Settings`): `metrics_enabled` (default `True` — unlike
tracing, metrics are meant to be always-on; `/metrics` simply renders a
placeholder body if the library isn't installed or the flag is off, so
this default never breaks a deployment without Prometheus set up),
`metrics_path` (default `/metrics`), `metrics_worker_port` (default
`9101`, the Kafka worker's own metrics listener).

**`/metrics` endpoint** (`app/main.py`): a plain route added directly in
`create_app()`, deliberately outside `api_router`/`api_v1_prefix` — no
JSON envelope, no AgentABI JWT dependency (this is a local/internal-
network scrape target, not an authenticated API client; a production
deployment should firewall it at the network layer rather than expect
per-request auth here — that's the documented security boundary from
spec §6), and `include_in_schema=False` so it never appears in the
OpenAPI/Swagger surface.

**HTTP middleware** (`app/core/metrics_middleware.
PrometheusMetricsMiddleware`, added outermost in `create_app()`'s
middleware stack so its timing covers every other middleware layer):
records `agentabi_http_requests_total`/`_request_duration_seconds`
(method, route template, status) and `agentabi_http_requests_in_progress`
(method only — the route isn't resolved until routing runs partway
through the request, so the in-progress gauge can't be labeled by it
without a race).

**Metric families** (full list and label vocabulary in `app/
observability/metrics.py`'s module docstring and declarations):
- HTTP: requests/duration/in-progress (above).
- Analysis pipeline: `agentabi_analysis_runs_total`/`_duration_seconds`
  (pipeline=compatibility/replay/differential/risk/
  github_pr_analysis, status=success/failure) — recorded in the same
  five service-boundary wrapper methods Phase 15's spans already use
  (`CompatibilityService.run_scan`, `RiskService.run_assessment`,
  `ReplayService.execute_replay`, `DifferentialService.run_analysis`,
  `GitHubPullRequestAnalysisService.run_analysis`).
- Risk decisions (mandatory, spec §8/§38): `agentabi_risk_decisions_
  total{decision, hard_block}` + `agentabi_risk_score` (bucketed
  histogram, unlabeled) — `RiskService.run_assessment` calls
  `record_risk_decision(decision=record.decision,
  hard_block=record.hard_block, score=record.score)` using the
  already-persisted record's own fields; nothing in the metrics path
  ever calls `evaluate()` or constructs a `RiskContext`. `tests/
  test_risk_metrics_mandatory.py` asserts this structurally.
- Kafka: `agentabi_kafka_published_total`/`_publish_duration_seconds`,
  `agentabi_kafka_consumed_total`/`_processing_duration_seconds`,
  `agentabi_kafka_retries_total`, `agentabi_kafka_dlq_total` — all
  labeled by `event_type`/bounded `outcome`/`reason`, never event
  id/partition/offset. `tests/test_kafka_metrics_regression.py` (spec
  §39, mandatory) asserts the envelope schema, header-only trace
  propagation, partition key, idempotency, retry policy (no commit on
  a bare transient retry), DLQ routing, and commit policy are all
  unchanged by the added metric calls.
- Worker: `agentabi_worker_in_progress{event_type}` gauge helper
  (`track_worker_in_progress`, available for future use); the worker's
  own `start_worker_metrics_server(settings)` opens a dedicated
  `prometheus_client.start_http_server()` listener on `metrics_worker_
  port` since the worker isn't a FastAPI process (spec §14).
- GitHub: `agentabi_github_webhook_deliveries_total{event, outcome}`
  (`app/api/v1/github_webhook.py`), `agentabi_github_pr_analyses_
  total{outcome}` (started/completed/failed —
  `GitHubPullRequestAnalysisService`), `agentabi_github_check_publish_
  total{action, outcome}` + `agentabi_github_api_failures_
  total{action}` (`checks_client.py`'s create/update calls) — never
  repository name, PR number, or head SHA as a label.
- OpenAI: `agentabi_openai_explanations_total`/`_explanation_duration_
  seconds{outcome, model}` — `model` is the small, operator-configured
  `openai_model` setting, not user input, so it stays bounded.
  `tests/test_openai_metrics_regression.py` (spec §40, mandatory)
  asserts `_explain_impl` itself is untouched by the metrics wiring and
  that exceptions still propagate (never swallowed by the `finally`
  block that records duration).
- Errors: `agentabi_errors_total{error_type}` — bounded to
  `validation|dependency|timeout|internal`, mapped from the HTTP status
  code each exception handler already resolves to
  (`app/api/v1/errors.py`); an unrecognized category is coerced to
  `internal` rather than accepted as an arbitrary label value.
- Dependency (declared, not yet wired to a call site — spec §18's
  "only if useful, never fabricated"): `agentabi_dependency_requests_
  total`/`_request_duration_seconds{dependency, outcome}`, broad
  success/failure/latency only, available for a future phase to attach
  to Postgres/Redis/Neo4j boundaries without inventing new metric
  families then.

**Prometheus + Grafana (local, `docker-compose.yml`)**: `observability/
prometheus.yml` scrapes `api:8000/metrics` and the newly-containerized
`worker:9101/metrics` (the Kafka worker had never been added as a
compose service before this phase — same image as `api`, `python -m
app.kafka.worker`), no credentials, no remote_write. `observability/
grafana/provisioning/` auto-provisions Prometheus as Grafana's default
datasource and auto-loads `observability/grafana/dashboards/agentabi-
overview.json` (14 panels — HTTP rate/error-rate/p95 latency, per-
pipeline analysis throughput/p95 duration, PASS/WARN/BLOCK rate, risk-
score heatmap, hard-block count, Kafka publish/consume throughput, Kafka
retries/DLQ, GitHub PR analysis outcomes, GitHub check-publish failures,
OpenAI p95 latency/failure rate, errors by category) so `docker compose
up` produces a working dashboard with zero manual clicking. `grafana`
runs on host port `3001` (3000 is already the frontend); `GF_SECURITY_
ADMIN_PASSWORD` defaults to a documented local-only placeholder
(`GRAFANA_ADMIN_PASSWORD` env override, never a real secret committed).

**Failure-open** (spec §24, same posture as Phase 15): every metric
factory/recording function catches all exceptions and logs a warning
rather than raising; `GET /api/v1/ready` has no metrics dependency, and
`METRICS_ENABLED=false` skips every recording call without needing
`prometheus_client` importable at all.

**Verification**: `prometheus-client` is a pure-Python wheel but, like
every other dependency in this project, could not be installed in this
sandbox this session (PyPI unreachable). All observability code is
written, `ruff format --check`/`ruff check`/`python3.12 -m py_compile`
clean; new tests are written/`py_compile`-clean, not pytest-executed.
`docker compose config` validates the added `worker`/`prometheus`/
`grafana` services; the dashboard JSON validates via `json.load`, and
all three new/changed YAML files validate via `yaml.safe_load`. No real
local observability smoke test was produced — the Docker daemon is
unavailable in this sandbox (confirmed directly in Phase 14), so it was
honestly skipped rather than fabricated.

## Phase 17: Terraform AWS Infrastructure

**Purpose**: an infrastructure-as-code foundation AgentABI can be
deployed onto for a recruiter/portfolio demo — genuinely production-
architected, but built around a provision-for-a-demo/destroy-afterward
lifecycle rather than a service that runs continuously. Phase 17 creates
infrastructure only: no Kubernetes objects, no Helm releases, no
AgentABI application containers, no Neo4j. That is Phase 18. See
`infra/terraform/README.md` for the full writeup (architecture diagram,
module responsibilities, network topology, security model, secrets
strategy, remote-state bootstrapping, MSK cost warning, and the complete
START/DEMO/SHUTDOWN/DESTROY/RECREATE lifecycle) and ADR-086 for why this
shape was chosen over keeping managed infrastructure online continuously.

**Layout**: `infra/terraform/modules/{networking,eks,iam,ecr,rds,redis,
msk,secrets,dns}` (nine single-purpose modules), `infra/terraform/
environments/dev` (the root module wiring them together with
cost-conscious defaults), `infra/terraform/bootstrap` (a standalone root
module for the optional S3+DynamoDB remote-state backend — applied, if
ever, separately and manually, never as part of `dev`, to avoid a
backend that depends on infrastructure managed through that same
backend).

**Network**: a three-tier VPC (public / private-app / private-data) per
AZ. EKS worker nodes and every managed data service (RDS, ElastiCache,
MSK) live in private subnets with no public IP and no inbound path from
the internet; security groups scope ingress to the EKS cluster's own
additional security group only. NAT is a configurable cost/availability
trade-off (`single_nat_gateway`, default `true`) rather than a fixed
choice — see `infra/terraform/README.md`'s "Networking cost trade-off".

**IAM / IRSA**: every AWS-facing Kubernetes workload gets its own IAM
role, assumable only via the EKS cluster's OIDC provider by a specific
namespaced ServiceAccount — never a broad node-instance role, never a
wildcard `AdministratorAccess`-style policy. `modules/iam` prepares roles
for the AWS Load Balancer Controller (Phase 18 installs the controller
itself), the EBS CSI driver (for Neo4j's persistent storage in Phase 18),
cluster-autoscaler, and AgentABI's own API/worker pods — the last scoped
to read-only access to exactly AgentABI's own ECR repositories and
Secrets Manager secrets, nothing else.

**Credentials never touch Terraform**: RDS uses `manage_master_user_password
= true` — AWS creates, stores, and rotates the master password in
Secrets Manager directly; Terraform only ever holds the resulting secret
*ARN*. `modules/secrets` creates empty `aws_secretsmanager_secret`
containers for the application's own secrets (JWT signing key, OpenAI API
key, GitHub OAuth/App credentials) with no `aws_secretsmanager_secret_
version` resource anywhere — values are populated out-of-band after
`apply`, and none of the local `.env` development secrets were copied
into this code. ElastiCache's AUTH token is left disabled by default
rather than generated by Terraform (which would place a credential in
state); the cache instead relies on network isolation alone.

**MSK**: both managed-Kafka deployment modes the Terraform AWS provider
currently supports are implemented — `aws_msk_serverless_cluster`
(`deployment_mode = "serverless"`, the cost-conscious default: no fixed
broker cost while idle between demos) and `aws_msk_cluster`
(`"provisioned"`, the classic always-on broker-per-AZ deployment) — both
authenticate via SASL/IAM rather than long-lived SASL/SCRAM credentials.
Kafka/MSK itself is never swapped for a non-Kafka substitute to save
cost; only the deployment mode is configurable.

**DNS is fully optional**: `modules/dns` produces zero resources and
every output is `null` when `domain_name = ""` (the default) — the rest
of the stack validates and is fully usable without a custom domain, and
no domain name is invented anywhere in this codebase.

**A Terraform pitfall worth naming**: several modules conditionally
create a resource via `count = <condition> ? 1 : 0` and then need to
reference its attribute elsewhere only when that condition holds.
Writing that as `condition ? foo.this[0].attr : null` is a well-known
trap — Terraform can raise "index out of range" on the branch that isn't
even logically selected, once `foo.this` has zero instances, because the
`[0]` index is invalid to construct as an expression regardless of which
ternary branch is chosen. Every such site in this codebase
(`modules/dns`, `modules/msk`, `modules/iam`, `modules/redis`) uses
`one(foo.this[*].attr)` (safe: splatting a count-0 resource yields an
empty list, and `one()` maps a 0-or-1-element list to `null`-or-the-
element) instead.

**Verification**: honestly incomplete — no `terraform` binary is
installable in this sandbox (HashiCorp's release host returns 403
through this session's network egress policy, the same restriction that
has blocked every non-PyPI/npm package install all session). `terraform
fmt`/`init`/`validate`/`tflint` were not run and that is reported as such
rather than fabricated; static review (brace/paren balance, cross-
checking every module argument and output against that module's
declarations, duplicate-label and undeclared-variable scans, and the
`[0]`-indexing fix above) was done in its place. Run `terraform fmt
-check -recursive`, `terraform init -backend=false`, and `terraform
validate` from `infra/terraform/environments/dev` locally before
`apply`.
