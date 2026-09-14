# Roadmap

Status tracker for the 20-phase build order. Update the table at the end of
every phase.

| # | Phase | Status |
|---|-------|--------|
| 1 | Repository foundation + local Docker environment | ✅ Done (see caveat in DECISIONS.md ADR-005) |
| 2 | PostgreSQL + SQLAlchemy + Alembic | ✅ Done (see caveat in DECISIONS.md ADR-006/ADR-008) |
| 3 | Component Registry | ✅ Done (see caveat in DECISIONS.md ADR-013) |
| 4 | Neo4j dependency graph | ✅ Done (see caveat in DECISIONS.md ADR-021) |
| 5 | Compatibility / schema-diff engine | ✅ Done (see caveat in DECISIONS.md ADR-022) |
| 6 | Trajectory recording | ✅ Done (see caveat in DECISIONS.md ADR-032) |
| 7 | Replay engine | ✅ Done (see caveat in DECISIONS.md ADR-036) |
| 8 | OpenAI provider | ⬜ Not started |
| 9 | Gemini provider | ⬜ Not started |
| 10 | Differential analyzer | ⬜ Not started |
| 11 | Deterministic risk engine | ⬜ Not started |
| 12 | GitHub integration | ⬜ Not started |
| 13 | Kafka / event-driven processing | ⬜ Not started |
| 14 | Frontend | ⬜ Not started |
| 15 | OpenTelemetry | ⬜ Not started |
| 16 | Prometheus + Grafana | ⬜ Not started |
| 17 | Terraform | ⬜ Not started |
| 18 | AWS deployment | ⬜ Not started |
| 19 | CI/CD | ⬜ Not started |
| 20 | Benchmarks + README + diagrams + demo prep | ⬜ Not started |

Security work (layered onto the phases above, tracked separately):

| # | Security Phase | Status |
|---|-----------------|--------|
| A | Authentication foundation (JWT) | ✅ Done (see caveat in DECISIONS.md ADR-037) |
| B | GitHub OAuth2 | ✅ Done (see caveats in DECISIONS.md ADR-039/040) |
| C | RBAC / project authorization | ⬜ Not started |
| D-F | (rate limiting, webhook security, audit, docs — as scoped when reached) | ⬜ Not started |

## Phase 1 notes

Repository structure, FastAPI skeleton, settings, structured logging,
correlation-ID middleware, health endpoint, Docker Compose local infra
(Postgres/Redis/Neo4j/Kafka), Ruff + mypy + pytest config, and doc
scaffolding (`docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`,
`docs/DECISIONS.md`, this file) are in place.

`pip install`, `pytest`, `mypy` against real deps, and `docker build`/`up`
were **not** runnable inside this sandbox (no PyPI egress, no Docker
daemon — see ADR-005). Ruff and syntax checks passed; `docker compose
config` validated the compose file schema. Run `make install && make lint
&& make typecheck && make test && make infra-up` locally to complete
verification before starting Phase 2.

## Phase 2 notes

Async SQLAlchemy engine/session (`app/core/database.py`), ORM base +
`UUIDPrimaryKeyMixin`/`TimestampMixin` (`app/models/base.py`), four
foundational tables (`organizations`, `users`, `projects`,
`organization_members`), a hand-written async Alembic environment
(`backend/alembic/`), the initial migration (`0001_initial_schema.py`),
and a `/api/v1/ready` endpoint that actually probes the database (503 on
failure) are in place.

Same PyPI/Docker sandbox restriction as Phase 1 (ADR-005/ADR-006): the
Python driver stack (SQLAlchemy, asyncpg, Alembic) could not be installed,
so `pytest`/`mypy` against real deps and `alembic upgrade head` were not
runnable here. Unlike Phase 1, PostgreSQL itself **was** available as a
system package in this sandbox, so the migration's DDL was verified by
direct execution against a real database, including every constraint
(unique slug, unique `(organization_id, slug)`, unique membership, cascade
delete) — see ADR-008. Ruff (format + lint) and `python -m py_compile`
passed clean on every new file.

Run `make install && make lint && make typecheck && make test` and then
`cd backend && ../backend/.venv/bin/alembic upgrade head` (against the
`docker compose`-managed Postgres, or any real Postgres 16+) locally to
complete verification before starting Phase 3.

## Phase 3 notes

Versioned Component Registry: `components` (identity) +
`component_versions` (immutable JSONB content snapshots) tables
(`0002_component_registry.py`), ten `ComponentType`s with per-type Pydantic
content validation (`app/domain/component_content.py`), deterministic
SHA-256 checksums (`app/domain/checksums.py`), a Postgres trigger blocking
version content mutation, `ComponentRegistryService` with full CRUD/list/
latest-version logic and tenant isolation, thin repositories
(`Component`/`ComponentVersion`/`Project`), a domain exception hierarchy
mapped centrally to HTTP responses, and paginated REST endpoints under
`/api/v1/projects/{project_id}/components`.

Same PyPI/Docker sandbox restriction as Phases 1-2 (ADR-013): `pytest`/
`mypy` against real deps and `alembic upgrade` were not runnable here.
Migrations 0001+0002 were hand-transcribed and applied together against
real Postgres 16, and every new constraint/behavior (duplicate slug+type
rejection, same slug allowed across types, auto-incrementing `sequence`,
duplicate version rejection, the immutability trigger, cascade delete) was
exercised directly and passed. Ruff (format + lint) and `python -m
py_compile` passed clean on every new file.

Run `make install && make lint && make typecheck && make test && make
migrate` locally to complete verification before starting Phase 4.

## Phase 4 notes

Neo4j dependency graph and blast-radius foundation: `DependencyRelationshipType`
(10 members) + a closed `(source_type, relationship_type, target_type)`
allow-list (`app/domain/relationship_rules.py`), an async Neo4j driver
singleton (`app/graph/client.py`), a `GraphRepository` Protocol +
`Neo4jGraphRepository` with all Cypher and idempotent schema
initialization (`app/graph/repository.py`), `DependencyGraphService`
(Postgres→Neo4j sync, dependency create/delete/list with validation and
tenant scoping), a pure-Python BFS `BlastRadiusService` with explicit
cycle/depth/dedup handling, a pluggable readiness-check registry
extending `/api/v1/ready` to cover both Postgres and Neo4j, thin REST
endpoints under `/api/v1/projects/{project_id}/graph/...`, and new domain
errors (`GraphComponentNotFound`, `InvalidDependencyRelationship`,
`GraphUnavailable`) mapped centrally to HTTP.

Same PyPI/Docker sandbox restriction as Phases 1-3, and this phase also
specifically needed (and could not get) a running Neo4j — see
DECISIONS.md ADR-021 for exactly what was attempted (a working Docker
daemon this session, but `registry-1.docker.io` pulls return 403; the Mac
device-bridge VM has no Docker, Python 3.10 only, and blocked network) and
the exact commands to complete verification later. Unlike Phases 1-3, no
Python dependency at all (`fastapi`, `sqlalchemy`, `neo4j`, ...) could be
installed in this sandbox this session either, so the actual `pytest`
suite did not run. What did run for real: ruff (format + lint) clean,
`python3.12 -m py_compile` clean on every file, and — via a lazy `neo4j`
import that keeps `GraphRepository` importable without the driver
installed — a standalone script genuinely exercising
`BlastRadiusService`/`relationship_rules` against the in-memory
`FakeGraphRepository`, 26/26 checks passing (cycle termination and
deduplication on a 3-node cycle, correct dependency/dependent direction,
depth and path tracking, `max_depth` cutoff, tenant isolation,
deterministic ordering).

Run `make install && make lint && make typecheck && make test` and
`docker compose -f docker-compose.yml up -d neo4j && pytest
tests/test_graph_repository.py -v` locally to complete verification
before starting Phase 5.

## Phase 5 notes

Deterministic Compatibility/Schema-Diff Engine: a pure, stdlib-only
`app/compatibility/` package (`models.py`, `schema_normalizer.py`,
`rules.py`, `diff.py`, `analyzer.py`) with no LLM in the decision path,
comparing a baseline and candidate `component_version` and reporting
structured `Change`s with an explicit directional (`INPUT`/`OUTPUT`/
`NEUTRAL`) classification and severity, dispatched per `ComponentType`
(Schema/Tool/MCP-server get full structural JSON-Schema diffing;
Prompt/Model/Agent get targeted field comparisons; Workflow/Policy/API
fall back to a generic config-diff; `PROVIDER` is explicitly
unsupported). New `compatibility_scans`/`scan_changes` tables
(`0003_compatibility_scans.py`) with an unconditional immutability
trigger, a `CompatibilityService` that always creates a new historical
scan row per run and enforces the same-component rule twice, and REST
endpoints under `/api/v1/projects/{project_id}/compatibility/scans`.

Same PyPI/Docker sandbox restriction as every prior phase, but this
phase's core engine is plain-dataclass Python with zero SQLAlchemy/
Pydantic/FastAPI imports, which made it possible to bypass
`tests/conftest.py` (`pytest --noconftest`) and run the real, installed
`pytest` binary directly: **75/75 pure unit tests passed**
(`test_schema_normalizer.py`, `test_rules.py`, `test_diff.py`,
`test_analyzer.py`), including the spec's exact acceptance-case example
(`authorize_payment(customer_id, amount, currency)` →
`authorize_payment(user_id, amount)`) run through the generic engine, not
hardcoded. Migration 0003 was verified by direct DDL execution against a
real local Postgres 16 (same ADR-008 pattern), including both
immutability triggers and cascade delete. `test_compatibility_service.py`
(15 tests) and `test_compatibility_api.py` (11 tests) are written and
`py_compile`-clean but need SQLAlchemy/FastAPI/httpx to actually run
through `pytest` — see DECISIONS.md ADR-022.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 6.

## Phase 6 notes

Trajectory Recording: a dataclass/stdlib-only `app/trajectory/` package
(`models.py`, `transitions.py`, `redaction.py`, `payload_limits.py`,
`hashing.py`, `validation.py`) plus new `trajectories`/`trajectory_events`
tables (`0004_trajectories.py`) recording historical agent-execution runs
as an ordered, append-only sequence of strongly-typed events (an 18-member
closed `EventType` enum — no free-form event strings anywhere). Sequence
numbers are allocated via a single atomic conditional `UPDATE` (never
`max()+1`), events carry an optional exact `component_version_id`
snapshot reference, redaction and payload-size limits run on every event,
dual idempotency covers both trajectory-start (`external_run_id`) and
event-append (`external_event_id` + content hash) retries, and
`TrajectoryRecorderService` exposes start/append/complete/fail/get/list
behind thin REST endpoints under
`/api/v1/projects/{project_id}/trajectories`. This phase deliberately
does not implement replay (Phase 7), OpenTelemetry (Phase 15), or S3
payload archival — see DECISIONS.md ADR-026 through ADR-030.

Same PyPI/Docker sandbox restriction as every prior phase, but the
`app/trajectory/` package has zero SQLAlchemy/Pydantic/FastAPI imports,
which again made it possible to bypass `tests/conftest.py`
(`pytest --noconftest`) and run the real, installed `pytest` binary
directly: **49/49 pure unit tests passed** (`test_trajectory_transitions.py`,
`test_trajectory_redaction.py` — including the spec's exact
secret-redaction acceptance case — `test_trajectory_payload_limits.py`,
`test_trajectory_validation.py`, `test_trajectory_hashing.py`,
`test_trajectory_models.py`), and combined with Phase 5's 75, **124/124
passed**, confirming no regression. Migration 0004 was verified by direct
DDL execution against a real local Postgres 16 (same ADR-008 pattern),
including the spec's exact 8-event `checkout-run-8291` acceptance
trajectory, both immutability postures (trigger on `trajectory_events`,
none on `trajectories`), the sequence/external-run-id unique constraints,
and cascade delete. While fixing `conftest.py` for this phase's trigger,
a latent Phase 5 gap was found and fixed — see DECISIONS.md ADR-031.
`test_trajectory_recorder_service.py` (24 tests, incl. a real
`asyncio.gather` concurrency test) and `test_trajectories_api.py` (16
tests) are written and `py_compile`-clean but need SQLAlchemy/FastAPI/
httpx to actually run through `pytest` — see DECISIONS.md ADR-032.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 7.

## Phase 7 notes

Deterministic Replay Engine: a dataclass/`Protocol`-only `app/replay/`
package (`models.py`, `transitions.py`, `planner.py`, `executor.py`)
plus new `replay_runs`/`replay_steps` tables (`0005_replays.py`).
`build_replay_plan()` classifies each historical event as reused,
substituted (baseline->candidate, historical arguments preserved),
provider-required (model events — no adapter until Phase 8/9), or
skipped (a substituted call's superseded response), always in
`sequence_number` order. `ReplayService` computes the plan once at
creation, then `execute_replay()` inserts each `ReplayStep` exactly once
already in its final status — never insert-then-update — via a pluggable
`ExecutorRegistry` that ships empty in production (no executor wired
means `ReplayExecutorUnavailable`, never a fabricated result).
`FakeReplayExecutor` proves the orchestration in tests. Idempotency
mirrors Phase 6's pattern exactly. Does not implement replay execution
against real providers/tools (later phases) or behavioral differencing
(Phase 10) — see DECISIONS.md ADR-033 through ADR-035.

Same sandbox restriction as every prior phase. `app/replay/` ran for
real via `pytest --noconftest`: **25/25 new pure unit tests passed**
(incl. the spec's exact 7-event checkout acceptance case — v6 invoked
with v5's historical arguments, original trajectory untouched);
combined with Phase 5/6's 124, **149/149 passed**. Migration 0005
verified by direct DDL against real Postgres 16: the acceptance-case
plan, both immutability postures (trigger on `replay_steps`, none on
`replay_runs`), sequence/idempotency-key uniqueness, and cascade delete
from `trajectories`. `test_replay_service.py` and `test_replays_api.py`
are written and `py_compile`-clean but not pytest-executed — see
DECISIONS.md ADR-036.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 8.

## Security Phase A notes

Authentication foundation: a stdlib-only HS256 JWT implementation
(`app/auth/jwt.py`, `app/auth/claims.py` — no PyJWT/authlib, same
install restriction as every phase's deps), a typed `AuthenticatedPrincipal`
(`app/auth/principal.py`) built by `get_current_user`
(`app/api/deps/auth.py`) which decodes the bearer token, reloads the
user, checks `is_active`, and — if the token carries an `org_id` —
reloads the caller's role from `OrganizationMember` on every request
rather than trusting a role claim (ADR-038). `GET /api/v1/auth/me`
(`app/api/v1/auth.py`) is the one protected endpoint, returning an
explicit `AuthMeResponse` that cannot serialize secrets. Reused Phase
2's existing `OrganizationRole` (OWNER/ADMIN/MEMBER) rather than
renaming to ADMIN/ENGINEER/VIEWER — no functional gap, and renaming a
migrated enum is a breaking change for no benefit (ADR-037). No new
models, no migration: `users.is_active` already existed from
migration 0001. New auth errors (`AuthenticationRequired`,
`InvalidToken`, `ExpiredToken`, `UnknownUser`, `DisabledUser`) map to
401 with `WWW-Authenticate: Bearer` via the existing centralized error
handler. Does not implement GitHub OAuth, RBAC enforcement, or rate
limiting — deferred to Security Phases B-F.

Same sandbox restriction as every prior phase. `app/auth/jwt.py` and
`app/auth/claims.py` are genuinely pure and ran for real via
`pytest --noconftest`: **12/12 new unit tests passed** (valid/expired/
malformed/wrong-signature/wrong-issuer/wrong-audience/missing-claim/
alg-confusion cases); combined with the prior 149 pure tests,
**161/161 passed**, confirming no regression. `app/auth/principal.py`
imports `OrganizationRole` from `app.models`, which pulls in SQLAlchemy
via package init, so `test_auth_principal.py` and `test_auth_api.py`
are written and `py_compile`-clean but not pytest-executed here. No
migration was created — `users.is_active` already satisfies the only
DB-facing requirement.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Security Phase B.

## Security Phase B notes

GitHub OAuth2 login: `GET /auth/github/login` (random `state`, Redis-
backed TTL store, minimal `read:user user:email` scopes) redirects to
GitHub; `GET /auth/github/callback` validates+consumes `state` first,
exchanges `code`, fetches the GitHub identity (matched by GitHub's
immutable numeric id, never `login`), resolves/creates the `User`,
decides org context (exactly-one-membership only — ADR-040), and issues
a normal Phase A JWT. GitHub's access token is used once and discarded
— never persisted, logged, or returned. `users.github_user_id`/
`github_login` added via migration `0006`; state-failure and GitHub-
provider errors get 7 new centralized error types (ADR-039). Does not
implement RBAC enforcement, project authorization, rate limiting,
webhook security, or GitHub API scopes beyond login — deferred to
Security Phases C-F.

Same sandbox restriction as every prior phase (`redis`/`httpx` not
installable). `app/auth/oauth_state.py` has no SQLAlchemy/FastAPI/redis
import and ran for real via `pytest --noconftest`: **8/8 new pure unit
tests passed**; combined with the full existing pure suite,
**189/189 passed**, confirming no regression. Migration `0006`'s DDL
(add columns, unique constraint, index, downgrade) was verified by
direct execution against real Postgres 16. `test_github_oauth_service.py`
(8 tests, via `FakeGitHubOAuthClient`) and `test_github_oauth_api.py`
(5 tests, GitHub mocked) are written and `py_compile`-clean but not
pytest-executed here — need SQLAlchemy/FastAPI/httpx.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Security Phase C.
