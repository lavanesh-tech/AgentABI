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
