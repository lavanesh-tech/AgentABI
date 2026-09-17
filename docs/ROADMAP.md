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
| 17 | Terraform AWS Infrastructure | ✅ Done (see DECISIONS.md ADR-086) |
| 18 | CI/CD Foundation | ✅ Done (see DECISIONS.md ADR-087) — order swapped with #19, see note below |
| 19 | AWS Deployment | ⬜ Not started |
| 20 | Final production/recruiter validation and release | ⬜ Not started |

Phase order note: #18 and #19 were deliberately swapped from this
table's original phase numbering (Terraform → AWS deployment → CI/CD) to
Terraform → CI/CD → AWS deployment, so the CI/CD pipeline and Helm chart
exist *before* anything is actually deployed to AWS, rather than being
retrofitted onto a live environment. The GitHub repository's first
remote push is deliberately last of all, after Phase 20's security
review — see docs/DECISIONS.md ADR-087 and `infra/terraform/README.md`'s
"Phase 17 / 18 / 19 boundary".

Security work (layered onto the phases above, tracked separately):

| # | Security Phase | Status |
|---|-----------------|--------|
| A | Authentication foundation (JWT) | ✅ Done (see caveat in DECISIONS.md ADR-037) |
| B | GitHub OAuth2 | ✅ Done (see caveats in DECISIONS.md ADR-039/040) |
| C | RBAC / project authorization | ✅ Done (see ADR-041/042) |
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

## Security Phase C notes

RBAC and tenant isolation: `app/authz/permissions.py` maps OWNER >
ADMIN > MEMBER to explicit `Permission` sets (MEMBER read-only; ADMIN
adds engineering writes; OWNER adds membership/org management).
`require_project_permission(Permission.X)` (`app/api/deps/authz.py`)
authorizes against the `project_id` every project-scoped router already
takes, applied via `dependencies=[...]` to components/compatibility/
trajectories/replays/graph routes — no per-route authorization code,
and nested resources inherit isolation for free since every repository
already scopes lookups by `project_id`. `AuthorizationService`
(`app/authz/service.py`) always reloads membership fresh from Postgres
for the target resource's organization, never trusting
`AuthenticatedPrincipal.role` or a caller-supplied org id. Cross-tenant
denial is 404 (indistinguishable from not-found); in-tenant permission
denial is 403 (ADR-042). A minimal `Project` CRUD API
(`app/api/v1/projects.py`) ships as an authorization-testing surface.
Membership-mutation policy (`app/authz/membership.py`) exists and is
tested but has no route yet (ADR-041). Does not implement an audit-
event table (Phase E), Redis rate limiting, or service-account auth —
deferred.

Same sandbox restriction as every prior phase. `app/authz/permissions.py`
and `app/authz/membership.py` have no SQLAlchemy/FastAPI import and ran
for real via `pytest --noconftest`: **19/19 new pure unit tests
passed** (exhaustive role x permission matrix, membership policy incl.
last-owner protection); combined with the full existing pure suite,
**208/208 passed**, confirming no regression. `test_authz_service.py`
(7 tests: stale-JWT, membership-removal, cross-org denial) and
`test_organization_isolation_api.py` (17 tests: two-org isolation,
nested-resource isolation, full role matrix) are written and
`py_compile`-clean but not pytest-executed here — need SQLAlchemy/
FastAPI/httpx. No migration was needed — Phase C adds no schema
changes.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Security Phase D.

## Security Phase D — API Hardening (2026-09-14)

Redis-backed fixed-window rate limiting (fail-closed, ADR-043) applied
to GitHub OAuth login/callback, compatibility scan creation, replay
creation/execution, and trajectory creation/append via reusable
dependencies. Environment-aware CORS (never wildcard+credentials),
security response headers (no CSP at this layer — ADR-045; HSTS only in
production), a raw-ASGI request-size limit (413, webhook-safe —
ADR-046), and a standardized `{"error": {code, message, request_id}}`
envelope replacing the old `{"detail": ...}` shape across every domain
exception, FastAPI validation error, and unhandled exception. Does not
implement GitHub webhook HMAC verification or persistent audit logging
— deferred to Security Phase E, per spec.

Same sandbox restriction as every prior phase (no SQLAlchemy/FastAPI/
httpx/redis-py). New pure modules (`app/core/rate_limit.py`,
`app/core/cors.py`) ran for real via `pytest --noconftest`: **18/18 new
pure unit tests passed**; combined with the full existing pure suite,
**226/226 passed**, confirming no regression. The Redis algorithm itself
was exercised against a real local Redis server via raw `redis-cli
EVAL` (atomic increment, TTL, threshold enforcement, independent
principals, reset-after-expiry, and cross-invocation shared state
proving distributed correctness) since the Python `redis` client isn't
installable here. Four integration test files (error envelope, security
headers, request size, serialization security) are written and
`py_compile`-clean but not pytest-executed — need SQLAlchemy/FastAPI/
httpx. `ruff format --check`/`ruff check` clean; `python3.12 -m
py_compile` clean across `app`/`tests`; `mypy` fails on the same
pre-existing `pydantic.mypy` error as every prior phase. No migration
was needed — Phase D adds no schema changes.

Run `make install && make lint && make typecheck && make test` locally
to complete verification before starting Security Phase E.

## Security Phase E — GitHub Webhook Security and Audit (2026-09-14)

`POST /api/v1/github/webhook`: HMAC-SHA256 signature verification over
raw body bytes (ADR-047), delivery-id idempotency with SHA-256
payload-hash conflict detection (ADR-048), rate limited and
request-size-protected but unauthenticated by AgentABI JWT. Persistent
append-only `audit_events` (immutable via DB trigger, tenant-scoped,
redacted metadata — ADR-049) with an OWNER/ADMIN-only read API at
`GET /api/v1/organizations/{organization_id}/audit-events`. Audit
emission wired at two centralized points: GitHub OAuth login success/
failure, and authorization denials. Does not implement GitHub PR/check
processing, compatibility-scan triggering from webhooks, or release
gate logic — deferred to a later product phase (Phase 12).
`PROJECT_CREATED`/`SCAN_TRIGGERED`/`REPLAY_TRIGGERED` exist in the
audit taxonomy but are not yet emitted — scoped out this phase (see
ADR-049).

Same sandbox restriction as every prior phase (no SQLAlchemy/FastAPI/
httpx). New pure modules (`app/github/webhook_signature.py`,
`app/audit/actions.py`) ran for real via `pytest --noconftest`: **11/11
new pure unit tests passed**; combined with the full existing pure
suite (one existing test updated for the new `AUDIT_READ` permission),
**237/237 passed**, confirming no regression. Migration 0007
(`audit_events`, `github_webhook_deliveries`) was verified against a
real local Postgres via raw `psql` (mirrors ADR-008's pattern, since
SQLAlchemy isn't installable here): unique-constraint duplicate
rejection, audit append, immutability trigger blocking both UPDATE and
DELETE, and the tenant-scoped `(organization_id, created_at)` index —
all confirmed live, then the scratch database was dropped. Five
integration test files (webhook idempotency, audit service, audit API,
webhook API, plus the existing Phase D suites) are written and
`py_compile`-clean but not pytest-executed — need SQLAlchemy/FastAPI/
httpx. `ruff format --check`/`ruff check` clean; `python3.12 -m
py_compile` clean across `app`/`tests`/`alembic`; `mypy` fails on the
same pre-existing `pydantic.mypy` error as every prior phase.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Security Phase F.

## Phase 8 — OpenAI Provider Integration: COMPLETE

## Phase 9 — Gemini Provider Integration: SKIPPED / OPTIONAL

## Phase 10 — Differential Analyzer: NEXT

Adds `app/llm/`, `app/providers/{openai_provider,fake_provider}.py`,
`app/services/explanation_service.py`, `app/api/deps/llm.py`, and one
endpoint: `POST .../compatibility/scans/{scan_id}/explain`. OpenAI-only
project decision (Gemini intentionally not implemented — see
docs/DECISIONS.md ADR-050); the `LLMProvider` Protocol keeps the
architecture ready for another provider without a rewrite. See
docs/ARCHITECTURE.md's Phase 8 section for the full design and
docs/DECISIONS.md ADR-050/051/052.

Same sandbox restriction as every prior phase: `openai` (like fastapi/
sqlalchemy) isn't installable here, and `pytest-asyncio` also isn't
installable, so none of this project's `async def test_*` functions run
in this sandbox regardless of phase. Pure, synchronous logic ran for
real this phase: `app/llm/bounding.py`'s truncation/clipping rules, and
an AST-based architectural-invariant test proving no deterministic
package imports `openai` and that `openai` is imported nowhere outside
`app/providers/openai_provider.py` — **8/8 passed**. `ruff format
--check`/`ruff check` clean; `python3.12 -m py_compile` clean across
`app`/`tests`. `docker compose config` and the migration chain were not
re-checked this phase (no schema change — Phase 8 added no tables).

Run `make install && make lint && make typecheck && make test` locally
(with a real `OPENAI_API_KEY` if you want to exercise the live endpoint)
to complete verification before starting Phase 10.

## Phase 8 — OpenAI Provider Integration: COMPLETE

## Phase 9 — Gemini Provider Integration: SKIPPED / OPTIONAL

## Phase 10 — Differential Analyzer: COMPLETE

## Phase 11 — Deterministic Risk Engine: COMPLETE

## Phase 12 — GitHub PR / Release Integration: COMPLETE

## Phase 13 — Kafka Event Pipeline: COMPLETE

## Phase 14 — Frontend Dashboard: COMPLETE

## Phase 15 — OpenTelemetry: COMPLETE

## Phase 16 — Prometheus + Grafana: COMPLETE

## Phase 17 — Terraform AWS Infrastructure: COMPLETE

## Phase 18 — CI/CD Foundation: COMPLETE

Gemini (Phase 9) remains SKIPPED/OPTIONAL.

## Phase 15 — OpenTelemetry: COMPLETE (detail)

Adds `backend/app/observability/` (`tracing.py`, `propagation.py`,
`redaction.py`) — the single module every other file imports from
rather than touching `opentelemetry.*` directly. `OTEL_ENABLED=false` by
default (spec §5): a disabled/uninstalled process never imports the SDK
at all (ADR-071), so nothing about this phase can break existing
behavior. Traces the path `GitHub Webhook -> FastAPI -> Kafka Producer ->
Kafka -> Worker -> Compatibility/Replay/Differential/Risk -> Postgres/
Neo4j/Redis -> GitHub API -> optional OpenAI explanation`: FastAPI
auto-instrumentation (`FastAPIInstrumentor`, idempotent per app
instance), SQLAlchemy auto-instrumentation on the engine, manual domain
spans at five service boundaries (`agentabi.compatibility.analyze`,
`agentabi.replay.execute`, `agentabi.differential.analyze`,
`agentabi.risk.evaluate`, `agentabi.github.pr_analysis`) added by
wrapping each entrypoint around a renamed `_*_impl` rather than
importing OTel into `app/risk/`'s pure engine (ADR-072), manual
producer/consumer spans (`agentabi.kafka.publish`/`.consume`) with
mandatory W3C trace-context propagation through Kafka **headers only**
(`app/observability/propagation.py`; envelope schema/partition key/
idempotency/commit policy byte-for-byte unchanged — ADR-072), manual
client spans around the GitHub checks client (`github.check.create`/
`.update`), GitHub OAuth exchange (`github.oauth.exchange`), the OpenAI
provider boundary (`agentabi.openai.explain`), the Neo4j repository's
single `_run` Cypher boundary (`neo4j.query`, operation = leading Cypher
keyword only, never full Cypher/params), and Redis rate-limit/OAuth-
state boundaries (no key/state value ever attached). `app/core/
logging.py` gained a `_add_trace_context` processor enriching every log
line with `trace_id`/`span_id` when a span is active, alongside (never
replacing) the existing `correlation_id`. The standalone Kafka worker
(`app/kafka/worker.py`) initializes/shuts down its own tracer provider
independently of FastAPI, with `service.name=agentabi-worker` vs the
API's `agentabi-api`. `docker-compose.yml` gained an `otel-collector`
service (`otel/opentelemetry-collector-contrib`, config at
`observability/otel-collector-config.yaml`, stdout-only exporter, no
credentials) that the API/worker are never `depends_on` — spec §28:
readiness never depends on collector availability. See docs/
ARCHITECTURE.md's Phase 15 section and docs/DECISIONS.md ADR-071/
ADR-072.

Same sandbox restriction as every prior phase, now confirmed to also
cover `opentelemetry-*`: `pip install opentelemetry-api` returns "No
matching distribution found" — PyPI itself is unreachable in this
sandbox (not just compiled/network-heavy packages), so none of the
declared `opentelemetry-api/-sdk/-exporter-otlp-proto-http/
-instrumentation-fastapi/-httpx/-sqlalchemy` dependencies could be
installed or exercised. Every module touching them (all of `app/
observability/`, and every call site listed above) is written and
`python3.12 -m py_compile`-clean, and `ruff format --check`/`ruff check`
are clean across the full `app`/`tests` tree (`259 files unchanged`, `0`
lint errors after one `--fix` pass for import-sorting/quoted-annotation
style). `mypy` is unavailable (`No module named mypy`), same as every
phase. New tests — `tests/test_observability_redaction.py` (pure stdlib,
would run under plain `pytest` with no project dependencies once
`pytest` itself is installed — it isn't, in this sandbox, this session),
`tests/test_observability_propagation.py` (asserts the documented no-op
path: `inject_trace_headers()` returns `[]`, `extract_trace_context`
returns `None` for missing/empty/malformed headers, never raises),
`tests/test_observability_log_correlation.py`, `tests/
test_kafka_trace_regression.py` (the mandatory spec §35 check —
structural assertions via `inspect.getsource` that the publisher/
consumer inject/extract via Kafka `headers=`, never touch
`event.metadata` or the serialized envelope bytes), and `tests/
test_observability_domain_spans.py` (needs the real SDK + Postgres via
the `session` fixture — an in-memory span exporter asserting
`agentabi.compatibility.analyze` is emitted and the scan result is
unchanged) — are all written/`py_compile`-clean, not pytest-executed.
`docker compose config` validates cleanly with the new `otel-collector`
service added (confirmed by direct invocation, not assumed). No real
trace smoke test was attempted — §42 requires both installable
dependencies and a running collector; neither is available here, so it
was honestly skipped rather than fabricated.

Run `cd backend && pip install -e ".[dev]" && pytest && cd .. && docker
compose up -d otel-collector api worker` locally, with `OTEL_ENABLED=true`,
to complete verification and produce a real trace before starting
Phase 16.

## Phase 16 — Prometheus + Grafana: COMPLETE (detail)

Adds `backend/app/observability/metrics.py` (Phase 16 spec §5's "extend,
don't scatter" — same `app/observability/` package as Phase 15's
tracing, deliberately separate module: `prometheus_client` for metrics,
`opentelemetry` for traces, never mixed — ADR-073). `METRICS_ENABLED=true`
by default, `METRICS_PATH=/metrics` (`app/core/config.py`); the API
exposes it as a plain, unauthenticated (no AgentABI JWT — spec §6's
documented security boundary, meant for a local/internal-network
scraper), OpenAPI-excluded route added directly in `create_app()`, never
routed through the JSON error envelope. `app/core/metrics_middleware.py`
(`PrometheusMetricsMiddleware`, added outermost in the middleware stack)
records `agentabi_http_requests_total`/`_duration_seconds`/
`_in_progress`, labeled by method + the Starlette route *template*
(`request.scope["route"].path`) — never the raw resolved path, which is
what keeps an unmatched/probed route from exploding cardinality (it
collapses to a single `"unmatched"` label instead).

Every metric name/label vocabulary lives in one file
(`app/observability/metrics.py`); every other module calls small
`record_*()` helpers re-exported from `app.observability`, never
`prometheus_client` directly. Cardinality safety (spec §22, mandatory)
is enforced at metric-registration time — `_assert_safe_labels()` raises
if any declared labelname is in the explicit forbidden set
(`project_id, organization_id, component_id, event_id, trace_id,
request_id, correlation_id, pull_request_number, head_sha, email,
github_username, url, exception[_message]`) — and re-verified statically
by `tests/test_metrics_cardinality_safety.py` via AST inspection
(ADR-074).

Instrumented alongside the existing Phase 15 spans, never replacing
them: `agentabi_analysis_runs_total`/`_duration_seconds` (pipeline=
compatibility/replay/differential/risk/github_pr_analysis, status=
success/failure) at the same five service-boundary wrapper methods Phase
15 already uses; `agentabi_risk_decisions_total` (decision, hard_block)
+ `agentabi_risk_score` (bucketed histogram, no labels) recorded in
`RiskService.run_assessment` from the already-persisted `record`'s own
`decision`/`hard_block`/`score` fields — never recomputed, verified by
the **mandatory** `tests/test_risk_metrics_mandatory.py` (spec §8/§38);
Kafka publish/consume/retry/DLQ counters and duration histograms in
`kafka_publisher.py`/`app/kafka/consumer.py` (event_type/outcome labels
only — never event_id/partition/offset), regression-checked by `tests/
test_kafka_metrics_regression.py` (spec §39: envelope/headers/partition
key/idempotency/retry/DLQ/commit policy all unchanged); GitHub webhook-
delivery/PR-analysis/check-publish counters in `github_webhook.py`/
`github_pr_analysis_service.py`/`checks_client.py` (action/outcome
labels — never repository name/PR number/SHA); OpenAI explanation
counters/duration in `openai_provider.py` (outcome + model — the model
is a small operator-configured set, not user input), regression-checked
by `tests/test_openai_metrics_regression.py` (spec §40: `_explain_impl`
itself is untouched, exceptions still propagate through the metrics
`finally` block rather than being swallowed); a bounded `agentabi_errors_
total{error_type}` (validation|dependency|timeout|internal, mapped from
HTTP status code — never raw exception text) wired into `app/api/v1/
errors.py`'s existing exception handlers.

The Kafka worker (`app/kafka/worker.py`) is not a FastAPI process, so it
calls `prometheus_client.start_http_server()` directly on its own port
(`METRICS_WORKER_PORT=9101`, spec §14) rather than sharing the API's
`/metrics` route — `docker-compose.yml` gained a `worker` service (same
image as `api`, `python -m app.kafka.worker`, first time this worker has
been containerized) exposing that port. `observability/prometheus.yml`
(new) scrapes `api:8000/metrics` and `worker:9101/metrics`, no
credentials, no remote_write. `observability/grafana/provisioning/`
(new) auto-provisions Prometheus as Grafana's default datasource and
auto-loads `observability/grafana/dashboards/agentabi-overview.json` (14
panels: HTTP rate/error-rate/p95 latency, per-pipeline analysis
throughput/p95 duration, PASS/WARN/BLOCK rate, risk-score heatmap,
hard-block count, Kafka publish/consume throughput, Kafka retries/DLQ,
GitHub PR analysis outcomes, GitHub check-publish failures, OpenAI p95
latency/failure rate, errors by category) — `docker compose up` produces
a working dashboard with zero manual clicking. `docker-compose.yml`
gained `prometheus` (`:9090`) and `grafana` (`:3001` on the host — 3000
is already the frontend) services with local-only placeholder Grafana
admin credentials (`GRAFANA_ADMIN_PASSWORD`, default documented as
local-only, never a real secret).

Same sandbox restriction as every prior phase, now confirmed to also
cover `prometheus-client`: `pip install prometheus-client` returns "No
matching distribution found" — PyPI itself is unreachable in this
sandbox this session. Every touched/added module is `python3.12 -m
py_compile`-clean, and `ruff format`/`ruff check` are clean across the
full `app`/`tests` tree (one `--fix` pass for import ordering). `mypy`
fails immediately on the `pydantic.mypy` plugin import (pydantic itself
isn't installed) — same as every prior phase; `pytest` fails at
`conftest.py` collection (`httpx` isn't installed) — also same as every
prior phase. New tests (`test_metrics_helpers.py`,
`test_metrics_cardinality_safety.py`, `test_http_metrics_middleware.py`,
`test_risk_metrics_mandatory.py`, `test_kafka_metrics_regression.py`,
`test_openai_metrics_regression.py`) are written/`py_compile`-clean, not
pytest-executed. `docker compose config` validates cleanly with
`worker`/`prometheus`/`grafana` added (confirmed by direct invocation).
Dashboard JSON validated via `json.load`; all three new/changed YAML
files validated via `yaml.safe_load` (PyYAML happens to be present in
this sandbox, unlike every project dependency). No real local
observability smoke test was attempted — the Docker daemon itself is
unavailable in this sandbox (confirmed directly in Phase 14), so it was
honestly skipped rather than fabricated, same posture as Phase 15's
trace smoke test.

Run `cd backend && pip install -e ".[dev]" && pytest && cd .. && docker
compose up -d` locally to complete verification, hit a few routes, curl
`http://localhost:8000/metrics`, confirm the `agentabi-api`/`agentabi-
worker` targets show UP at `http://localhost:9090/targets`, and open
`http://localhost:3001` (admin / the configured password) to see the
provisioned "AgentABI — System Overview" dashboard before starting Phase
17.

## Phase 18 — CI/CD Foundation: COMPLETE (detail)

CI/CD foundation only (ADR-087) — no AWS resources created, no
`terraform apply`, no image pushed to any registry, no `helm install`
against a real cluster, no push to GitHub. Adds `.github/workflows/ci.yml`
(automatic on every push/PR: backend lint/format/mypy/pytest against real
Postgres+Neo4j service containers, frontend lint/typecheck/build/vitest,
Terraform fmt/init/validate for both the `dev` and `bootstrap` roots,
Gitleaks secret scanning + Trivy dependency/IaC scanning, and a
push-nothing Docker build-verification job for both Dockerfiles) and
`.github/workflows/deploy.yml` (manual `workflow_dispatch`-only CD:
build+push to ECR with immutable git-SHA tags → `helm upgrade --install
--atomic` → rollout verification, every job gated by a GitHub
Environment with required reviewers — see ADR-087 for why this is never
automatic). Adds `infra/terraform/modules/github-oidc` (disabled by
default — no real GitHub org/repo exists yet) for GitHub Actions → AWS
OIDC federation, replacing any notion of static `AWS_ACCESS_KEY_ID`/
`AWS_SECRET_ACCESS_KEY` GitHub secrets, and sets
`authentication_mode = API_AND_CONFIG_MAP` on the Phase 17 EKS cluster
resource so an EKS Access Entry can grant that role RBAC scoped to the
`agentabi` namespace without a Kubernetes/Helm Terraform provider. Adds
the first Kubernetes manifests in this repository:
`deploy/helm/agentabi`, a Helm chart covering the API/worker/frontend
Deployments, a Neo4j StatefulSet with an EBS-backed PVC, a
`SecretProviderClass` (AWS Secrets Store CSI Driver), and a database
migration Job wired as a Helm pre-upgrade hook (runs once, before any
Deployment is touched; `--atomic` rolls the release back if it fails).
Adds `.github/dependabot.yml` for GitHub Actions/pip/npm, grouped by
minor/patch to limit PR noise.

Full detail — including the exact secrets-sync mechanism (mounting the
CSI volume is what triggers the Secrets Manager → Kubernetes Secret
sync, so the migration Job and both Deployments all mount it even though
only `envFrom` is read from) and the Phase 17/18/19 boundary — is in
`docs/ARCHITECTURE.md`'s Phase 18 section and `infra/terraform/README.md`.

**Verification**: `ruff check`/`ruff format --check` ran for real
against the backend and passed cleanly. `mypy`, `pytest`, the frontend's
`npm install`/lint/typecheck/build/test, `terraform fmt`/`init`/
`validate`, `actionlint`, and a real Docker image build were all
attempted and could not complete in this sandbox — each for a specific,
confirmed reason (missing installable Python/npm runtime dependencies;
no `terraform` binary; `proxy.golang.org` and `registry-1.docker.io` not
actually reachable despite appearing permitted) — documented in full,
including exactly what non-fabricated substitute checks were run
instead (YAML parsing, manual Terraform static review continuing Phase
17's methodology, manual Helm template review), in
`docs/ARCHITECTURE.md`'s Phase 18 Verification paragraph. Nothing here
is reported as passing that did not actually run.

## Phase 17 — Terraform AWS Infrastructure: COMPLETE (detail)

Infrastructure-as-code only (ADR-086) — no AWS resources created, no
`terraform apply` run, no Kubernetes application deployment. Adds
`infra/terraform/`: nine modules (`networking`, `eks`, `iam`, `ecr`,
`rds`, `redis`, `msk`, `secrets`, `dns`), the `environments/dev` root
module wiring them together, and a standalone `bootstrap/` module for the
optional S3+DynamoDB remote-state backend (never applied against AWS this
phase; local state remains the default so `terraform init -backend=false`
needs no AWS access at all).

Three-tier VPC (public / private-app / private-data) with a cost-vs-
availability NAT toggle (`single_nat_gateway`, default `true`: one NAT
Gateway total, vs. one per AZ). EKS: KMS-encrypted control plane secrets,
private worker nodes, OIDC provider for IRSA, one managed node group with
configurable instance types/capacity type/scaling. IAM: every AWS-facing
workload (Load Balancer Controller, EBS CSI driver, cluster-autoscaler,
AgentABI's own API/worker pods) gets its own IRSA role scoped to a
specific Kubernetes ServiceAccount — no broad node-wide permissions, no
`AdministratorAccess`-style policy anywhere; the AgentABI app role is
further scoped to only its own ECR repos and Secrets Manager secrets.
RDS Postgres uses `manage_master_user_password = true` (AWS-managed
Secrets Manager password) rather than any Terraform-held credential, with
a documented disposable-vs-snapshot-preserving destroy trade-off
(`skip_final_snapshot`). ElastiCache (Redis or Valkey, `redis_engine`)
relies on network isolation rather than generating an AUTH token in
Terraform state, by default. MSK supports both deployment modes the AWS
provider exposes — `serverless` (default, cost-conscious, no idle broker
cost) and `provisioned` (production-style, continuous broker cost) —
selected by `msk_deployment_mode`, never replaced by a non-Kafka
substitute. `modules/secrets` creates only empty Secrets Manager
containers; no `aws_secretsmanager_secret_version` resource exists
anywhere in this phase, and none of the local `.env` values were copied
in. `modules/dns` is fully optional (`domain_name = ""` by default) — no
domain name is invented, and the rest of the stack validates and is
usable without one.

New ADR-086 explains the ephemeral/on-demand demo lifecycle rationale;
`infra/terraform/README.md` documents architecture, module
responsibilities, network topology, security model, secrets strategy,
remote-state bootstrapping, the MSK cost warning, and the full START /
DEMO / SHUTDOWN / DESTROY / RECREATE lifecycle with an explicit table of
which resources merely scale down vs. must be destroyed to stop billing
(no fabricated dollar figures — links to AWS's own pricing pages instead).

**Verification**: no `terraform` binary is installable in this sandbox
(HashiCorp's release host, like every non-PyPI/npm host, returns 403
through this session's egress proxy — confirmed directly, same standing
sandbox restriction as every prior phase's package-install attempts) —
`terraform fmt`, `terraform init`, `terraform validate`, and `tflint`
could not actually be run, and that is reported honestly rather than
fabricated. In their place: every `.tf`/`.json` file was checked for
brace/parenthesis balance; every module argument passed from
`environments/dev/main.tf` was cross-checked against that module's
declared variables (no typos); every module output referenced from the
`dev` root was cross-checked against that module's declared outputs; no
duplicate resource/data/module/output labels; no `var.*` reference
without a matching declaration. A specific, well-known Terraform pitfall
was found and fixed during this review: indexing a `count`-conditional
resource with a literal `[0]` inside a ternary (e.g. `var.x ? foo.this[0].y
: null`) can raise "index out of range" even on the branch that isn't
logically selected, once `foo.this` has zero instances — every such site
(`modules/dns`, `modules/msk`, `modules/iam`, `modules/redis` outputs)
was rewritten using the safe `one(foo.this[*].y)` / splat-and-`flatten()`
idiom instead. This is static review, not a substitute for actually
running `terraform validate` — do that locally before `apply`.

## Phase 14 — Frontend Dashboard: COMPLETE (detail)

Adds `frontend/` — a standalone Next.js 14 (App Router) + TypeScript
(strict) + Tailwind + TanStack Query + React Flow + Recharts dashboard,
independently runnable from the backend. Covers every route in spec §7
(`/login`, `/dashboard`, `/projects`, `/projects/[projectId]`,
`/projects/[projectId]/components`, `/compatibility`, `/graph`,
`/trajectories`, `/replays`, `/differential`, `/risk`, `/github`,
`/audit`), a centralized typed API client (`lib/api-client.ts`) parsing
the standardized error envelope and handling 401 globally, one
TanStack Query hook module per implemented backend resource
(`features/*/hooks.ts`), and RBAC-aware UI via a frontend mirror of
`app/authz/permissions.py` (`lib/permissions.ts` — UX only, backend
remains authoritative). The dependency graph and blast-radius screen
renders real Phase 4 graph data via React Flow — no relationship or
impact tier is computed client-side. The risk screen is deliberately
the most prominent: PASS/WARN/BLOCK, score, threshold visualization,
hard-block indication, and the full rule-contribution trace, labeled
"Deterministic Deployment Risk"; the optional OpenAI explanation
(spec §24) is a manual "Generate AI Explanation" action, never
auto-called. See docs/ARCHITECTURE.md's Phase 14 section and
docs/DECISIONS.md ADR-069/ADR-070 for the OAuth token-handling and
PR-analysis read-endpoint decisions.

Backend gap closed before the frontend could be built honestly (spec
§1's "do not assume endpoints exist"): a subagent-assisted inventory of
every implemented API confirmed no read endpoint existed for
`GitHubPullRequestAnalysis` (written by the Phase 12/13 webhook
pipeline, never exposed over HTTP). Added the minimum necessary
surface — `GET /projects/{project_id}/github/pr-analyses` (paginated,
optional `pull_request_number` filter) and `GET .../{analysis_id}` —
following the existing repository/service/router layering, with no
change to the orchestration service's write path. `docs/DECISIONS.md`
ADR-071 has the full rationale.

Same sandbox network restriction as every backend phase, now also
covering the frontend: `npm install` returns `403 Forbidden` from the
registry (confirmed directly — same restriction class as PyPI/PyPI-hosted
`httpx`/`fastapi`/etc. throughout this project), so `npm run
lint`/`typecheck`/`test`/`build` and Playwright could not be executed
here. Every frontend/backend file is written and, for the backend
addition, `ruff format --check`/`ruff check`/`python3.12 -m py_compile`
clean; the new `GitHubPRAnalysisRepository.list_by_project` and
`GitHubPullRequestAnalysisService.list_analyses`/`get_analysis` tests
in `tests/test_github_pr_analysis_service.py` are written/`py_compile`-
clean, not pytest-executed (need SQLAlchemy/asyncpg, unavailable here —
same restriction documented for every integration test in this
project). Vitest unit tests (`frontend/tests/*.test.ts(x)`) cover API
error-envelope parsing (400/422/429 mapping, `NetworkError` on fetch
failure), PASS/WARN/BLOCK and hard-block rendering, rule-contribution
rendering, RBAC permission mapping (MEMBER/ADMIN/OWNER), and the
structured-diff component; a Playwright smoke suite
(`frontend/e2e/smoke.spec.ts`) covers login rendering, the
unauthenticated-redirect, an authenticated dashboard render, and a
mocked PASS/WARN/BLOCK risk render — written, not executed, per the
same restriction. Visual verification (spec §46) was skipped — the
dev server could not be started without a working `npm install`.
`docker compose config` (with the new `web` service added) validated
cleanly. `docker build ./frontend` could not run — the `docker` CLI is
present in this sandbox but its daemon is not running here
(`Cannot connect to the Docker daemon at unix:///var/run/docker.sock`).

Run `cd frontend && npm install && npm run lint && npm run typecheck &&
npm test && npm run build` locally to complete frontend verification
before starting Phase 15.

## Phase 13 — Kafka Event Pipeline: COMPLETE (detail)

Adds `app/events/` (envelope, errors, analysis_events, publisher,
fake_publisher, kafka_publisher, handler, factory — all dependency-free
except `kafka_publisher.py`/`factory.py`, which import `aiokafka` only
lazily/at their own module scope), `app/kafka/` (consumer, worker,
analysis_handler), a `start_analysis`/`run_analysis` split in `app/
services/github_pr_analysis_service.py`, a `KAFKA_ENABLED` branch in
`app/api/v1/github_webhook.py`'s dispatch step, a `kafka` readiness
check, 4 new audit actions, 1 new domain exception
(`GitHubAnalysisHeadShaMismatch`), the `aiokafka` dependency, and a
`make worker` target. Decouples event ingestion from analysis execution
via two Kafka topics (`agentabi.analysis.requests`/`.results`, plus a
`.dlq`) without moving any compatibility/risk logic into producers or
consumers — Phase 5/11's deterministic engines remain the sole source of
`decision`/`score`. See docs/ARCHITECTURE.md's Phase 13 section and
docs/DECISIONS.md ADR-063 through ADR-068.

Same sandbox restriction as every prior phase: `pytest-asyncio`,
SQLAlchemy, and (new this phase) `aiokafka`/`orjson` aren't installable
here — `app/events/envelope.py` deliberately uses stdlib `json` instead
of the already-declared `orjson` specifically so its serialization logic
could still run for real (ADR-068). Pure logic ran for real via `pytest
--noconftest`: event envelope construction/serialization/version
validation/round-trip (`tests/test_events_envelope.py`) and the full
analysis-event taxonomy including partition-key stability and the
no-secrets-in-schema assertion (`tests/test_events_analysis_events.py`)
— **28/28 passed**. Full sweep across every pure-runnable test in
`tests/`: **369 passed** (up from Phase 12's 341), no new failures
beyond the pre-existing async/FastAPI-dependent gaps every phase already
documents. `ruff format --check`/`ruff check` clean; `python3.12 -m
py_compile` clean across `app`/`tests`/`alembic`; `mypy` unavailable (`No
module named mypy`), same as every phase. `tests/test_events_fake_
publisher.py`, `tests/test_kafka_analysis_handler.py` (real-Postgres,
incl. duplicate-event idempotency and version/unknown-id rejection), and
new Phase 13 cases in `tests/test_github_pr_analysis_service.py`
(`start_analysis`/`run_analysis` split, head_sha-mismatch rejection —
the Phase 13 mandatory stale-SHA test, spec §38 — redelivery
idempotency, PUBLISH_FAILED retry-without-recompute) are written/
`py_compile`-clean, not pytest-executed (need `pytest-asyncio`/
SQLAlchemy). `app/kafka/consumer.py`/`app/events/kafka_publisher.py`
(both `aiokafka`-dependent) are written/`py_compile`-clean only; no
dedicated consumer unit test file, since the sandbox can't import
`aiokafka` at all — its retry/DLQ/poison-message classification logic is
documented in ARCHITECTURE.md and exercised indirectly through
`AnalysisRequestHandler`'s executable-elsewhere tests, which cover the
actual domain-error-to-retry-policy classification the consumer
dispatches on. No live Kafka broker exists in this environment — the
optional real-Kafka smoke test (spec §41) was honestly skipped, never
fabricated.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 14.

## Phase 12 — GitHub PR / Release Integration: COMPLETE (detail)

Adds `app/github/{checks_models,checks_client,checks_fake,check_mapping,
pr_webhook_models,pr_analysis_models}.py`, `app/models/
{github_repository_mapping,github_pr_analysis}.py`, migration 0010,
`app/repositories/{github_repository_mapping_repository,
github_pr_analysis_repository}.py`, `app/services/
{github_pr_analysis_service,github_repository_mapping_service}.py`,
`app/api/v1/github_repositories.py`, an additive dispatch step in the
existing `app/api/v1/github_webhook.py` route, 10 new domain exceptions,
4 new audit actions, and two new centralized permissions
(`GITHUB_INTEGRATION_READ`/`GITHUB_INTEGRATION_MANAGE`). Turns a GitHub
`pull_request` webhook into a deterministic Compatibility->Risk pipeline
run and publishes the PASS/WARN/BLOCK result back as a GitHub check run
— GitHub computes nothing; AgentABI's existing deterministic engines
remain solely authoritative. See docs/ARCHITECTURE.md's Phase 12 section
and docs/DECISIONS.md ADR-058 through ADR-062.

Same sandbox restriction as every prior phase: `pytest-asyncio` and
SQLAlchemy aren't installable here. Pure logic ran for real via `pytest
--noconftest`: check-conclusion mapping exhaustiveness and summary
content/distinctness, and webhook-payload parsing (supported/unsupported
actions, malformed/missing-field payloads) against a new sanitized
sample fixture (`tests/fixtures/github_pull_request_opened.json`) —
**28/28 passed**. Full sweep across every pure-runnable test in
`tests/`: **341 passed**, no new failures beyond the pre-existing async/
FastAPI-dependent gaps every phase already documents (confirmed `tests/
test_authz_permissions.py` still 12/12 green after the two new
permissions). `ruff format --check`/`ruff check` clean; `python3.12 -m
py_compile` clean across `app`/`tests`/`alembic`; `mypy` unavailable (`No
module named mypy`), same as every phase. `tests/
test_github_checks_client_fake.py` (async, `FakeGitHubChecksClient`) and
`tests/test_github_pr_analysis_service.py` (real-Postgres integration,
including the mandatory stale-SHA test) are written/`py_compile`-clean,
not pytest-executed (need `pytest-asyncio`/SQLAlchemy); no dedicated
`test_github_repository_mapping_api.py`, following Phase 10/11's own
precedent. No real GitHub credentials exist in this environment — the
live GitHub Checks API smoke test was honestly skipped, never
fabricated.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 13.

## Phase 11 — Deterministic Risk Engine: COMPLETE (detail)

Adds `app/risk/` (models, rules, engine — all dependency-free/pure),
`app/models/risk_{assessment,rule_result}.py`, migration 0009,
`app/repositories/risk_repository.py`, `app/services/risk_service.py`,
`app/api/v1/risk.py` (`POST/GET .../risk/assessments`, `GET
.../assessments/{id}`), and two new centralized permissions
(`RISK_READ`/`RISK_EXECUTE`). Deterministically composes compatibility,
differential, replay, and blast-radius evidence into a PASS/WARN/BLOCK
decision with a 0-100 score — never an LLM. See docs/ARCHITECTURE.md's
Phase 11 section and docs/DECISIONS.md ADR-056/057.

Same sandbox restriction as every prior phase: `pytest-asyncio` and
SQLAlchemy aren't installable here. Pure logic ran for real via `pytest
--noconftest`: every named rule, decision-threshold boundaries (exact
29/30/69/70/100), reproducibility, hard-block, score-cap, double-
counting-cap, deterministic ordering, and the AST-based no-LLM-
dependency test (extended `DETERMINISTIC_PACKAGES` to include `risk`
and `differential`) — **26/26 passed**. Adding `RISK_READ`/
`RISK_EXECUTE` required updating `tests/test_authz_permissions.py`'s
hardcoded expected sets in the *same* change this time (Phase 10's
regression lesson applied proactively) — still 12/12 green. Full sweep
across every pure-runnable test in `tests/`: **313 passed**, no new
failures beyond the pre-existing async/FastAPI-dependent gaps every
phase already documents. `ruff format --check`/`ruff check` clean;
`python3.12 -m py_compile` clean across `app`/`tests`/`alembic`; `mypy`
unavailable (`No module named mypy`), same as every phase.
`tests/test_risk_service.py` (real-Postgres integration) is
written/`py_compile`-clean, not pytest-executed (needs SQLAlchemy); no
dedicated `test_risk_api.py`, following Phase 10's own precedent.

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 12.

## Phase 10 — Differential Analyzer: COMPLETE (detail)

Adds `app/differential/` (models, alignment, value_diff, analyzer — all
dependency-free/pure), `app/models/differential_{report,change}.py`,
migration 0008, `app/repositories/differential_repository.py`,
`app/services/differential_service.py`, `app/api/v1/differential.py`
(`POST/GET .../differential/reports`, `GET .../reports/{id}`), and two
new centralized permissions (`DIFFERENTIAL_READ`/`DIFFERENTIAL_EXECUTE`).
Deterministically compares two COMPLETED replays' steps — never an LLM,
never a risk score. See docs/ARCHITECTURE.md's Phase 10 section and
docs/DECISIONS.md ADR-053/054/055.

Same sandbox restriction as every prior phase: `pytest-asyncio` and
SQLAlchemy aren't installable here. Pure logic ran for real via `pytest
--noconftest`: value-diff, step alignment, the end-to-end analyzer, and
the AST-based no-LLM-dependency test — **45/45 passed**. Fixing this
phase's two new `Permission` entries required updating
`tests/test_authz_permissions.py`'s hardcoded expected sets — a real
regression this session caught and fixed, not left unaddressed. Full
sweep across every pure-runnable test in `tests/`: **290 passed**, no
new failures beyond the pre-existing async/FastAPI-dependent gaps every
phase already documents. `ruff format --check`/`ruff check` clean;
`python3.12 -m py_compile` clean across `app`/`tests`/`alembic`; `mypy`
unavailable (`No module named mypy`), same as every phase.
`tests/test_differential_service.py` (real-Postgres integration) is
written/`py_compile`-clean, not pytest-executed (needs SQLAlchemy).

Run `make install && make lint && make typecheck && make test &&
alembic upgrade head` locally to complete verification before starting
Phase 11.
