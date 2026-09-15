# Architecture Decision Log

Short-form ADRs. Newest first.

## ADR-084 — First-organization onboarding: authenticated self-service `POST /organizations`, not DB seeding, a CLI, or admin-only bootstrap (supersedes ADR-040's deferred item) (2026-09-15)

**Context:** ADR-040 deliberately left a gap open: a GitHub-authenticated
user with zero `OrganizationMember` rows gets a valid AgentABI JWT with
`organization_id=None` and `requires_onboarding=True`, but nothing in
the codebase could ever turn that into an actual organization —
every org-scoped route (`app/api/deps/authz.py`'s
`require_organization_permission`/`require_project_permission`) requires
an *existing* organization to check membership against. A real local
user authenticated via GitHub OAuth and got stuck exactly here: zero
memberships, no route able to create the first one. Local verification
confirmed this by direct inspection of every model/repository/service/
route/migration/script/test/Postman file — no seeding script, CLI, or
admin-only bootstrap mechanism existed anywhere.

**Decision:** Close the gap with `POST /api/v1/organizations`
(`app/api/v1/organizations.py`), gated purely on "the authenticated
caller currently has zero organization memberships" — reloaded from the
database inside a locked transaction on every call, never trusted from
the JWT or the request body. A successful call atomically creates one
`Organization` and one `OrganizationMember(role=OWNER)` for the caller,
records an `AuditAction.ORGANIZATION_CREATED` event, and returns a fresh
AgentABI JWT carrying the new `organization_id` (still with no `role`
claim — authorization continues to reload role from `OrganizationMember`
on every request, exactly as before). `GET /auth/me` now also returns a
freshly recomputed `requires_onboarding` flag (not just the one-time
`GitHubCallbackResponse` field), so an already-authenticated session —
including one that predates this feature — discovers it needs to
onboard on its next `/auth/me` refresh rather than being stuck.

Three alternatives were rejected:

- **Raw database seeding / manual `INSERT`.** Not a supported product
  flow at all — it doesn't scale past one developer's local machine,
  requires direct DB access the frontend/API can never have in a real
  deployment, and leaves no audit trail.
- **A local-only CLI/management command.** Solves the developer's
  immediate local problem but not the actual product gap: a real
  deployed user hitting this same zero-membership state has no shell
  access to run a CLI. It would need to be reimplemented as an API
  endpoint eventually anyway.
- **An admin-only bootstrap endpoint.** Wrong shape for this specific
  gap — there is no pre-existing admin/OWNER role anywhere for a
  brand-new tenant to be bootstrapped *by*; requiring one begs the
  question. Onboarding must be something the orgless user themselves can
  do, authenticated only as themselves.

Authenticated self-service onboarding is the smallest fix that works
identically for the local developer and a real production sign-up: the
same authorization invariant (reload membership from the database, only
ever grant OWNER for a newly created organization, never let the client
assert a role/org id/other user's id) holds in both environments,
because it's the same code path.

**Concurrency:** the DB-level `uq_organization_members_org_user`
constraint prevents a user from getting two memberships in the *same*
organization but does nothing to stop two concurrent onboarding
requests for the same user from each observing zero memberships and
each creating a *different* new organization. `OrganizationRepository.
lock_user_for_onboarding` takes a `SELECT ... FOR UPDATE` lock on the
caller's own `User` row before the membership check, serializing
concurrent onboarding attempts for that one user without locking
anything that could block a different user's request.

## ADR-083 — Frontend dark mode: `data-theme` attribute stays the single source of truth; Tailwind's `darkMode` config fixed to match it (2026-09-15)

The frontend UI/UX polish checkpoint added a light/dark/system
`ThemeToggle`. `globals.css` already themed everything through CSS
custom properties keyed off a `[data-theme="dark"]` attribute on
`<html>` (with `@media (prefers-color-scheme: dark)` as the "system"
fallback when the attribute is absent) — but `tailwind.config.ts` had
`darkMode: "class"`, which only ever matches a `.dark` class ancestor.
No code added that class, so any `dark:` Tailwind utility would have
been silently inert. Rather than introduce a second theming mechanism
(a class toggle alongside the attribute one), `darkMode` was changed to
Tailwind 3.4's selector form, `["selector", '[data-theme="dark"]']`, so
`dark:` utilities key off the exact same attribute the CSS variables
already use — one source of truth, not two. `ThemeToggle` persists the
viewer's choice in `localStorage` (a per-viewer UI preference, same
category as `useCurrentProject`'s selection, not application data) and
a tiny inline script in the root layout applies it before first paint
to avoid a theme flash; "system" removes the attribute entirely so the
existing media-query fallback takes back over.

## ADR-082 — Grafana dashboard files mount as a sibling path, not nested under the read-only provisioning mount (2026-09-15)

Real local verification: `docker compose up` failed to start Grafana —
`error mounting ".../observability/grafana/dashboards" to
"/etc/grafana/provisioning/dashboards/files": create mountpoint ...
read-only file system`. The `grafana` service mounted
`./observability/grafana/provisioning` read-only at
`/etc/grafana/provisioning`, then separately mounted
`./observability/grafana/dashboards` at
`/etc/grafana/provisioning/dashboards/files` — a path nested *inside*
the first mount's target. Docker has to create that nested path as a
mountpoint before attaching the second bind mount, and can't do that
inside a filesystem it already mounted read-only.

Fixed by mounting the dashboards directory at a sibling path,
`/etc/grafana/dashboards`, instead — both bind mounts now attach
directly to the image's own `/etc/grafana` directory, neither nested
inside the other. Updated
`observability/grafana/provisioning/dashboards/provider.yml`'s `path:`
to match. No change to what's provisioned: the same datasource, the same
dashboard JSON, the same `grafana_data` named volume for persistence,
still fully self-hosted (no Grafana Cloud). Design rule: when Grafana
provisioning config and the dashboard files it references are mounted as
two separate bind mounts, keep their container targets siblings — never
nest one bind mount's target inside another read-only bind mount's
target. Enforced generally (any service, any bind mount) by
`tests/test_compose_bind_mounts.py`.

## ADR-081 — `worker` gets its own compose-level healthcheck; it no longer inherits `api`'s (2026-09-15)

Real local verification: the worker container ran and consumed from
Kafka correctly (successful fetches, `error_code=0`, successful
consumer-group heartbeats) but Docker still reported it `unhealthy`
(`FailingStreak: 283`, `curl: (7) Failed to connect to localhost port
8000`). `worker` and `api` build from the same Dockerfile/image — Compose
only overrides `command:` for `worker` (`python -m app.kafka.worker`
instead of `uvicorn`), not the image's baked-in
`HEALTHCHECK CMD curl -f http://localhost:8000/api/v1/health`. Without an
explicit `healthcheck:` override in the `worker` service, that image-level
check applied verbatim to a process that never starts uvicorn — the
worker could never pass health regardless of actual liveness.

Fixed by giving `worker:` in `docker-compose.yml` its own `healthcheck:`,
probing `http://localhost:9101/metrics` — the existing Prometheus metrics
server (`start_worker_metrics_server`, spec §14) that
`app.kafka.worker.main()` already starts early, independent of Kafka
connectivity. This is real process liveness (the worker process is up
and its own HTTP surface answers), deliberately not Kafka readiness —
Kafka connectivity/consumer-group health stays governed by Kafka's own
healthcheck and the consumer's existing retry/DLQ handling, not
conflated into this probe. `api`'s health behavior is unchanged: it still
relies solely on the image's Dockerfile `HEALTHCHECK`.

Design rule for any future service added to this shared image: a
Compose service that overrides `command:` to run something other than
uvicorn must also declare its own `healthcheck:`, or it silently
inherits an `api`-shaped one that means nothing for it. Enforced by
`tests/test_worker_healthcheck.py`.

Also fixed in the same commit: `aiokafka`'s per-request/fetch/heartbeat
logs at `DEBUG` (this project's local-dev default `LOG_LEVEL`) were
drowning out AgentABI's own logs. `logging.basicConfig(level=...)` sets
the *root* logger, so every library without its own explicit level —
aiokafka included — inherited `DEBUG` too, even though the intent of the
local-dev default was AgentABI's own code, not third-party wire-protocol
traces. `app.core.logging.configure_logging` now caps `aiokafka`'s logger
at `WARNING` specifically when `LOG_LEVEL=DEBUG` is in effect; a real
aiokafka problem still logs at `WARNING`+, and INFO/WARNING/ERROR
behavior (where this was never an issue) is unchanged.

## ADR-080 — every explicitly-created PostgreSQL enum uses `create_type=False` (2026-09-15)

Real local verification: a fresh `alembic upgrade head` failed on 0001
with `asyncpg.exceptions.DuplicateObjectError: type "organization_role"
already exists`, even against an empty database. `postgresql.ENUM(...)`
defaults to `create_type=True`, which registers its own automatic
`CREATE TYPE`/`DROP TYPE` on any table that uses it as a column type —
0001 already created `organization_role` explicitly
(`_organization_role.create(bind, checkfirst=True)`) before using it in
`op.create_table("organization_members", ...)`, so that table's own
automatic create fired a second, `checkfirst=False` `CREATE TYPE` for
the same name and collided with the one that had just succeeded, all
inside the same (Alembic-managed, transactional) migration.

The same pattern — a module-level `postgresql.ENUM(...)` explicitly
`.create()`'d, then reused as a column type — was already present in
migrations 0002, 0003, 0004, 0005, and 0007, so all thirteen enum
declarations across those five files got the same fix, not just 0001's.
Migration design rule going forward: any migration that explicitly
creates/drops a PostgreSQL enum (rather than relying solely on the
automatic table-triggered create) must declare it with
`create_type=False`, making the explicit `.create()`/`.drop()` calls the
one and only place that type is ever created or dropped. Enforced by
`tests/test_migration_enum_creation.py`, which fails if a future
migration explicitly `.create()`s an enum without `create_type=False`.

## ADR-079 — API image packages `alembic.ini`/`alembic/` alongside `app/` (2026-09-15)

Real local verification: `docker compose exec api alembic upgrade head`
failed with `FAILED: No config file 'alembic.ini' found, or file has no
'[alembic]' section`, so PostgreSQL had no schema and GitHub OAuth's
user lookup hit `UndefinedTableError: relation "users" does not exist`.
`alembic` was already a `pyproject.toml` dependency and installed in the
image, but the Dockerfile's `COPY` list only ever named `pyproject.toml`
and `app/` — `alembic.ini` (whose `script_location = alembic` and
`prepend_sys_path = .` both assume the migration chain sits alongside
`app/` at the image's `WORKDIR`) and the `alembic/` directory itself were
never in the image at all. Fixed by adding `COPY alembic.ini ./` and
`COPY alembic ./alembic` next to the existing `COPY app ./app`. No
automatic migration-on-startup was added — the architecture's existing
intent is an explicit operator-run `alembic upgrade head`, and this fix
only makes that command capable of finding its own configuration; it
changes nothing about when or whether migrations run.

## ADR-078 — structlog runs the full stdlib-backed pipeline, not `PrintLoggerFactory` (2026-09-15)

Real Docker verification found both the API and worker crashing on their
first log call: `structlog.stdlib.add_logger_name` reads `logger.name`,
but `app.core.logging.configure_logging` paired it with `logger_factory=
structlog.PrintLoggerFactory()` — `PrintLogger` has no `.name` attribute,
so `AttributeError: 'PrintLogger' object has no attribute 'name'` fired
on every single log line (API's `logger.info("startup", ...)`; worker's
`start_worker_metrics_server`'s `logger.info(...)`, and then its own
`except` block's `logger.warning(...)` failed the same way).

`get_logger`'s own return-type annotation was already `structlog.stdlib.
BoundLogger`, and `logging.basicConfig(...)` was already being called —
both signal the intended architecture was full stdlib-backed logging,
not `PrintLoggerFactory`'s bypass-stdlib-entirely mode; `PrintLoggerFactory`
was simply the wrong factory for a pipeline built around `structlog.
stdlib.*` processors. Fixed by switching to the matching stdlib pair:
`logger_factory=structlog.stdlib.LoggerFactory()` (real `logging.Logger`
instances, so `.name` exists) and `wrapper_class=structlog.stdlib.
BoundLogger` (replacing `make_filtering_bound_logger`, which is the
correct pairing for `PrintLoggerFactory`, not this one). Added
`structlog.stdlib.filter_by_level` as the first processor — the standard
recipe for this pairing, so disabled-level events skip the rest of the
chain instead of relying solely on the stdlib logger's own filtering
further down. JSON/console rendering, correlation IDs, Phase 15 trace/span
enrichment, and log levels are all unchanged — the renderer still produces
the final string, which the stdlib logger's handler (`"%(message)s"`
format, from the existing `logging.basicConfig`) writes through as-is.

## ADR-077 — `apache/kafka` healthcheck needs the absolute script path; it isn't on PATH (2026-09-15)

Real Docker verification of ADR-076's `apache/kafka:3.8.0` switch found
the broker itself started fine (`Kafka Server started` in logs) but
Compose marked it unhealthy: `/bin/sh: kafka-topics.sh: not found`
(exit 127). Unlike Bitnami's image, `apache/kafka` does not add
`$KAFKA_HOME/bin` to `PATH`, so the bare command name that worked under
Bitnami doesn't resolve here. Fixed by calling the script at its
absolute path, `/opt/kafka/bin/kafka-topics.sh`. The command itself is
unchanged (`--bootstrap-server localhost:9092 --list`) — it was already
a real metadata request against the broker's internal listener, not a
bare process check, so no change was needed to what the healthcheck
actually verifies, only to how it invokes the CLI.

## ADR-076 — Switch local Kafka image from `bitnami/kafka` to `apache/kafka` (supersedes ADR-001) (2026-09-15)

Real local Docker verification found `bitnami/kafka:3.8` unresolvable
(`failed to resolve reference "docker.io/bitnami/kafka:3.8": not
found`) — Broadcom's 2025 retention-policy change removed free/legacy
Bitnami tags from Docker Hub, so a previously-valid pinned tag stopped
existing. Rather than chase another Bitnami tag likely to face the same
fate, `docker-compose.yml`'s `kafka` service now uses `apache/kafka:
3.8.0` — the official image published by the Apache Kafka project
itself, with native KRaft support since 3.7 and no separate Zookeeper
container, same as ADR-001's original choice.

The only required change is the environment-variable prefix: Bitnami's
scripts read `KAFKA_CFG_*`; the Apache image's entrypoint reads plain
`KAFKA_*` (mapped directly to `server.properties` keys — `KAFKA_NODE_ID`
-> `node.id`, `KAFKA_LISTENERS` -> `listeners`, etc.), so every setting
carries over one-for-one with the same values (single node, KRaft
`broker,controller` combined role, `PLAINTEXT://kafka:9092` advertised
listener, `CONTROLLER://:9093` on the controller listener,
`api`/`worker`'s `KAFKA_BOOTSTRAP_SERVERS=kafka:9092` untouched). Three
single-node replication-factor settings (`KAFKA_OFFSETS_TOPIC_
REPLICATION_FACTOR`, `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR`,
`KAFKA_TRANSACTION_STATE_LOG_MIN_ISR`, all `1`) are now explicit because
this image's startup validation is stricter about replication factors
exceeding the broker count than Bitnami's was — Bitnami's implicit
single-node defaults happened to already satisfy this, so it was never
visible before. The data volume mount moved from Bitnami's
`/bitnami/kafka` to `/var/lib/kafka/data` (set via `KAFKA_LOG_DIRS`),
the image's own convention; the `kafka_data` named volume itself is
unchanged. Topics (`agentabi.analysis.requests/.results/.dlq`), the
two-topic-plus-DLQ strategy (ADR-067), partition-key behavior
(ADR-066), retry/DLQ semantics, and at-least-once delivery are all
application-level and untouched by this image swap — none of them
depend on which Kafka distribution runs the broker.

## ADR-075 — Frontend Docker image doesn't copy `public/`; it doesn't exist and nothing references it (2026-09-15)

The Phase 14 `frontend/Dockerfile`'s runner stage unconditionally ran
`COPY --from=builder /app/public ./public`, which fails the build
outright (`"/app/public": not found`) the moment there is no
`public/` directory — confirmed true for this app: no static assets, no
`next/image`/`<Image>` usage, no favicon, nothing under `app/` or
`components/` references a `/`-rooted public URL. Rather than adding a
placeholder file just to satisfy the COPY (which would ship a fake
asset for no functional reason and quietly mask a real missing-file bug
if `public/` is ever meant to exist), the COPY is removed outright. The
rest of the runner stage — full `.next` (non-standalone), full
`node_modules`, `package.json`, `npm run start` — was already
internally consistent with `next.config.mjs` having no
`output: 'standalone'`, so this was the only packaging break. Add the
`public/` COPY back if a real `public/` directory is introduced later.

## ADR-074 — Cardinality safety enforced at metric-registration time, not just by convention (2026-09-15)

Phase 16 spec §22 lists exact label names that must never appear on any
Prometheus metric (`project_id, organization_id, component_id, event_id,
trace_id, request_id, correlation_id, pull_request_number, head_sha,
email, github_username, url, exception`/`exception_message`). Rather than
relying on code review alone, `app/observability/metrics.py`'s
`_counter`/`_histogram`/`_gauge` factory functions call
`_assert_safe_labels()` against a `FORBIDDEN_LABEL_NAMES` frozenset
before ever constructing a `prometheus_client` metric — a labelname
violation raises at import time (fails loud, at process startup, not
silently at scrape time), and `tests/test_metrics_cardinality_safety.py`
statically re-verifies the same set via AST inspection of every declared
metric. HTTP request labels use the route *template*
(`request.scope["route"].path`, e.g. `/api/v1/projects/{project_id}`),
never the raw resolved path — this is what keeps an attacker probing
random URLs from becoming a cardinality-explosion vector, and unmatched
routes collapse to a single `"unmatched"` label rather than the raw path.

## ADR-073 — Prometheus client library owns metrics directly; OpenTelemetry stays trace-only (2026-09-15)

Phase 16 spec §33 requires metrics and tracing to stay architecturally
separate: `app.observability.tracing` (Phase 15) is the only module that
touches `opentelemetry.*`; the new `app.observability.metrics` (Phase 16)
is the only module that touches `prometheus_client`, and never routes
through OTel's own metrics API. Two libraries, two concerns, one
boundary each — this avoids coupling metric cardinality/bucket decisions
to whatever OTel's SDK metrics exporter happens to support, and keeps
Phase 15's tracing code completely untouched by this phase (no shared
mutable state, no combined initialization order to reason about). Both
modules share the same defensive posture: absent library -> no-op,
`*_ENABLED=false` -> no-op, any internal failure -> logged and swallowed,
never a request-breaking exception (spec §24).

## ADR-072 — Trace context in Kafka headers only, never the event payload; domain spans at service boundaries, not inside `app/risk/` (2026-09-14)

Phase 15 spec §10 is explicit that W3C trace context must travel in
Kafka message headers, never inside `EventEnvelope`. `app/events/
envelope.py`'s field set (`event_id, event_type, event_version,
occurred_at, correlation_id, project_id, organization_id, payload,
metadata`) is unchanged — `KafkaEventPublisher.publish` now also passes
`headers=inject_trace_headers()` to `send_and_wait`, and
`KafkaEventConsumer._process_one` extracts a parent context from
`message.headers` before starting its own span. This keeps the mandatory
Phase 13 regression true by construction, not by discipline: nothing
about the envelope schema, partition key, or commit logic changed, so
there's no risk of tracing accidentally coupling to idempotency
(`tests/test_kafka_trace_regression.py`).

Domain spans (`agentabi.compatibility.analyze`, `agentabi.risk.evaluate`,
`agentabi.replay.execute`, `agentabi.differential.analyze`,
`agentabi.github.pr_analysis`) are added by wrapping each service's
public entrypoint (`run_scan`, `run_assessment`, `execute_replay`,
`run_analysis`) around a renamed `_*_impl` method, rather than importing
`app.observability` into `app/risk/`, `app/compatibility/`, `app/
differential/`, or `app/replay/`'s pure modules. `app/risk/` in
particular stays exactly as architecturally isolated as `tests/
test_risk_architectural_invariant.py` already asserts (no SQLAlchemy/
Pydantic/LLM/OpenTelemetry import anywhere in that package) — spec §15's
explicit preference.

## ADR-071 — `app.observability` degrades to a true no-op, not a disabled-but-imported SDK, when OpenTelemetry isn't installed or `OTEL_ENABLED=false` (2026-09-14)

Every function in `app/observability/tracing.py` (`start_span`,
`setup_tracing`, `current_trace_context`, `instrument_*`) checks
`_otel_available()` (a bare `import opentelemetry.sdk.trace` inside a
`try/except ImportError`) before touching the SDK, and `setup_tracing`
additionally short-circuits on `settings.otel_enabled=False` before even
attempting that import. This means: (1) a process with
`OTEL_ENABLED=false` (the default) never imports `opentelemetry.*` at
all, so a missing package is never even a reachable code path — spec
§5's "must run normally when telemetry is disabled" holds structurally;
(2) `start_span(...)` always returns a valid context manager yielding
`None`, so every call site (`app/events/kafka_publisher.py`, every
service boundary, `app/github/checks_client.py`, etc.) never branches on
"is tracing on" — the code reads identically whether OTel is installed
or not; (3) `setup_tracing`/`instrument_fastapi_app`/etc. catch every
exception from SDK/exporter construction and log-and-continue rather
than raise, so a collector that's down, a bad `OTEL_EXPORTER_OTLP_
ENDPOINT`, or a partially-broken install can never fail API startup or
webhook/Kafka processing — spec §24's "observability must fail open."
This is the same defensive-import pattern `app/graph/repository.py`
(`neo4j`) and `app/core/redis.py` (`redis`) already use for dependencies
this sandbox can't install; `app.observability` applies it uniformly to
`opentelemetry-*` instead of inventing a separate convention.

## ADR-070 — Frontend OAuth token handoff: point `github_oauth_redirect_uri` at a frontend-owned callback route, no backend code change (2026-09-14)

`GET /auth/github/callback` (`app/api/v1/auth.py`) returns the AgentABI
JWT as a JSON response body — confirmed by reading it directly, not
inferred — with no redirect-with-token, no `Set-Cookie`, and no
frontend-origin-aware behavior in `GitHubOAuthService`/`github_oauth_
redirect_uri` (`app/core/config.py`, a single plain string used
identically by both `start_login`'s authorize-URL construction and
`handle_callback`'s code exchange). Redesigning this into a cookie- or
redirect-based flow was out of scope (spec §1/§8: inspect actual
behavior, don't assume/redesign). Instead, `github_oauth_redirect_uri`
is set (env/config only) to the frontend's own `/auth/callback` route.
GitHub redirects the browser there with `code`/`state`/`error`;
`frontend/app/auth/callback/page.tsx` forwards those same params to the
backend's callback endpoint via a client-side, unauthenticated fetch,
then stores the returned JWT. Zero backend code changes — the OAuth App
registered with GitHub, and the value of `github_oauth_redirect_uri`,
must both point at the frontend origin in every environment (documented
in `frontend/.env.example`'s sibling backend guidance and this ADR).

Token storage: `sessionStorage` (`frontend/lib/auth-storage.ts`), not
`localStorage` or an in-memory-only store. Given the backend hands back
a bearer token rather than an httpOnly cookie, there is no storage
option here that is safe from a same-origin XSS read — that exposure is
inherent to the existing backend contract, not something the frontend
can close without a backend change out of scope for this phase.
`sessionStorage` was chosen over `localStorage` because it is scoped to
one tab and cleared on tab close, narrowing (not eliminating) the
exposure window; it was chosen over in-memory-only state because losing
the session on every page refresh would make the dashboard unusable for
a recruiter/demo audience, undermining spec §2's purpose. This is
documented as an accepted, real tradeoff, not a security control.

## ADR-069 — New read-only `GET /projects/{project_id}/github/pr-analyses[/{id}]` endpoint; no write-path change (2026-09-14)

Phase 14's mandatory backend inventory (spec §1) found `GitHubPull
RequestAnalysis` rows are written by the Phase 12/13 webhook pipeline
(`GitHubPullRequestAnalysisService`) but were never exposed over HTTP —
no router, no list/get-by-id method on `GitHubPRAnalysisRepository`
beyond the internal `get_by_idempotency_key`/`get_by_id` the pipeline
itself uses. Spec §1/§16/§25/§26 explicitly allow adding "the minimum
necessary" read endpoint rather than redesigning the backend around the
frontend's needs. Added: `GitHubPRAnalysisRepository.list_by_project`
(paginated, optional `pull_request_number` filter, ordered newest-
first), `GitHubPullRequestAnalysisService.list_analyses`/`get_analysis`,
and `app/api/v1/github_pr_analyses.py` — same layering, same
`GITHUB_INTEGRATION_READ` permission, same pagination envelope shape as
every other list endpoint in this codebase. No change to `start_
analysis`/`run_analysis`/`_publish_result` or any other write-path
method. The router's service-construction dependency instantiates
`HttpxGitHubChecksClient` (never called on this read path — no method
here publishes a check) purely because the existing service constructor
requires one; this mirrors `app/api/v1/github_webhook.py`'s own
instantiation exactly, is a cheap no-I/O construction, and avoids
splitting `GitHubPullRequestAnalysisService` into a read/write pair for
one new router, which would have been a larger change than spec §1
sanctions.

## ADR-068 — `json`, not `orjson`, for event serialization even though `orjson` is an existing declared dependency (2026-09-15)

`app/events/envelope.py` needs deterministic (sorted-key) JSON
serialization for the Kafka event schema (spec §5/§23), and `orjson` is
already listed in `pyproject.toml` — but it is not installable in this
sandbox (same PyPI restriction as every other compiled dependency), and
this module is exactly the one Phase 13 needs to stay `pytest
--noconftest`-executable for its mandatory pure event-schema tests (spec
§35). Using stdlib `json.dumps(..., sort_keys=True, separators=(",",
":"))` instead keeps `serialize_envelope`/`deserialize_envelope`
runnable for real in this environment at zero behavioral cost — both
produce deterministic, compact JSON; `orjson` remains declared for
whatever future use it was originally added for, untouched.

## ADR-067 — Two-topic strategy: `agentabi.analysis.requests` / `agentabi.analysis.results`, plus one DLQ topic (2026-09-15)

Spec §7 explicitly warns against a topic per project/organization/PR/
event-subtype. Three event types (`requested`/`completed`/`failed`)
collapse to two topics by direction — requests flow one way, results
(both completed and failed) flow the other — via `app/events/publisher.
resolve_topic`, keyed off `event_type` rather than any per-tenant value.
A third topic, `agentabi.analysis.dlq`, holds messages that exhausted
retries or failed permanently (spec §21). Local Kafka relies on the
broker's default auto-create-topics behavior (`docker-compose.yml`'s
`kafka` service — `apache/kafka` as of ADR-076, previously `bitnami/
kafka` — never sets `AUTO_CREATE_TOPICS_ENABLE`, so it stays at Kafka's
own default of `true`) — explicit topic provisioning is deferred to
Terraform (a later phase), matching
spec §33's "do not overengineer production topic provisioning yet."

## ADR-066 — Partition key `github_repository_id:pull_request_number`; exact-SHA check remains the actual safety mechanism, not partition ordering (2026-09-15)

Spec §24/§25: all three event types for one PR share a partition key
(`app/events/analysis_events.partition_key`), so Kafka's per-partition
ordering guarantee at least *tends* to keep same-PR events in commit
order. This is deliberately treated as a convenience, not a guarantee
relied upon for correctness — a worker crash-and-redeliver, a consumer
group rebalance, or simple concurrent workers can still process events
out of order. The actual safety mechanism is structural: `GitHubPullRequestAnalysisService.run_analysis`'s exact-`head_sha` check (see ADR-065)
holds regardless of delivery order, which is why the mandatory stale-SHA
test (spec §38) constructs the out-of-order scenario directly rather
than relying on partition behavior to prevent it.

## ADR-065 — Kafka's at-least-once delivery: idempotency via persisted analysis status, not a separate dedup table (2026-09-15)

Spec §17 requires idempotent consumers under Kafka's at-least-once
semantics. Rather than track processed `event_id`s in a new table,
`GitHubPullRequestAnalysisService.run_analysis` reuses the persisted
`GitHubPullRequestAnalysis.status` state machine already introduced in
Phase 12: COMPLETED is a no-op on redelivery, FAILED is not auto-retried
(spec §20 — permanent errors aren't retried indefinitely), and
PUBLISH_FAILED retries the check *publish* only, reusing the already-
computed `risk_assessment_id`/`compatibility_scan_id` rather than
recomputing them (spec §28). This piggybacks on Phase 12's existing
`(github_repository_id, pull_request_number, head_sha, analysis_version)`
unique constraint for request-side idempotency (redelivered webhooks)
and adds status-based idempotency for the worker side (redelivered Kafka
messages) — no new schema.

## ADR-064 — `start_analysis`/`run_analysis` split lets `KAFKA_ENABLED` toggle without duplicating the Phase 12 pipeline (2026-09-15)

`GitHubPullRequestAnalysisService.analyze_pull_request` (Phase 12's
original single entrypoint) is now `start_analysis` (validate mapping,
persist a PENDING row — cheap, safe to run on the webhook request
thread) immediately followed by `run_analysis` (the actual compatibility
-> risk -> check-publish pipeline). `KAFKA_ENABLED=false` calls both
inline, in the same request, reproducing Phase 12's exact prior
behavior byte-for-byte; `KAFKA_ENABLED=true` calls `start_analysis` on
the webhook thread, publishes an event, and lets `app.kafka.worker` call
`run_analysis` later. This means the deterministic pipeline logic exists
in exactly one place regardless of which mode is active — no duplicated
"sync path" vs. "async path" implementation of compatibility/risk/check-
publishing (spec §3/§15).

## ADR-063 — `KAFKA_ENABLED` defaults to `false`; Kafka client construction is fully lazy (2026-09-15)

Spec §12 requires the deterministic core to keep working without Kafka,
and that Kafka must not make app startup fail unnecessarily in local/
unit-test scenarios. `Settings.kafka_enabled: bool = False` is the
default for every environment unless explicitly overridden.
`app/events/factory.get_event_publisher` and `app/core/readiness.
check_kafka_connection` both import `app.events.kafka_publisher`
(which imports `aiokafka`) lazily, inside function bodies, never at
module scope — so a process that never sets `KAFKA_ENABLED=true` never
needs `aiokafka` importable at all, matching every other optional/
uninstallable dependency's precedent in this sandbox (`httpx`, `openai`,
`neo4j`, `redis`). `/ready`'s `kafka` check returns `True` immediately
when disabled (spec §31) rather than skipping the key from the response
— an explicit, visible "not applicable," not a silent omission.

## ADR-062 — PR-analysis dispatch lives in the webhook route, not inside `GitHubWebhookService.process()` (2026-09-14)

Phase 12 wires GitHub PR analysis into the existing Security-Phase-E
webhook endpoint additively rather than editing `GitHubWebhookService.
process()` itself. The route calls `service.process()` first (unchanged
signature, unchanged tests), and only for an `accepted` `pull_request`
delivery does it call a new `_dispatch_pr_analysis(...)` helper, wrapped
in a broad `try/except AgentABIError`/`except Exception` that always
logs via `structlog` and never changes the webhook's own 202 response.
This decouples "the delivery was received" (the webhook's job, always
true on success) from "the PR check was successfully published" (best-
effort, independently retryable) — and, more importantly, keeps every
already-passing Phase E test (idempotency, HMAC, rate limiting) at zero
regression risk, since the security-critical service function is
untouched.

## ADR-061 — `github_pr_analyses` is not immutable-once-created, unlike `differential_reports`/`risk_assessments` (2026-09-14)

Migration 0010 adds no UPDATE-blocking trigger on `github_pr_analyses`,
diverging from the Phase 10/11 immutable-evidence pattern. This table
tracks *operational pipeline state* for one logical PR analysis
(`status`, `check_run_id`, `risk_assessment_id`, `publish_error`), which
legitimately mutates as the pipeline progresses (PENDING -> IN_PROGRESS
-> COMPLETED/FAILED/PUBLISH_FAILED) — it is not itself a piece of
deterministic evidence. The evidence it points to
(`compatibility_scan_id`, `risk_assessment_id`) remains immutable
through the existing Phase 5/11 tables; `github_pr_analyses` only ever
gains foreign keys to that evidence; it never recomputes or overwrites
it.

## ADR-060 — Candidate/baseline version contract: `component_id` + optional `baseline_version` + `head_sha`-as-candidate-version, not `.agentabi.yaml` fetched via the GitHub Contents API (2026-09-14)

Spec §19's "reality check" forbids inferring a candidate component
version from a raw git diff. Rather than fetch a repo-side config file
through the GitHub Contents API — a whole additional, untested-without-
real-GitHub surface — Phase 12 reuses Phase 5's existing version-string
identity directly: `GitHubRepositoryMapping.component_id` (admin-
configured, required) + optional `baseline_version` (defaults to the
component's latest registered `ComponentVersion`) + the PR's `head_sha`
used verbatim as the candidate `ComponentVersion.version` string. The
caller's CI is expected to register a `ComponentVersion` with
`version == head_sha` before triggering analysis; if none exists,
`MissingAgentABIConfiguration` is raised rather than guessed. This adds
zero new Phase 5 code (`ComponentRegistryService.
get_latest_component_version`, `CompatibilityService.run_scan` already
existed) and is fully deterministic and testable without any GitHub
API call.

## ADR-059 — Phase 12 orchestrates Compatibility -> Risk only; Replay/Differential are out of scope for the PR-analysis pipeline (2026-09-14)

`GitHubPullRequestAnalysisService` calls `CompatibilityService.run_scan`
then `RiskService.run_assessment(project_id, compatibility_scan_id=...)`
— it does not invoke Phase 7 replay or Phase 10 differential. Both
require a pre-existing recorded trajectory plus two completed replay
runs, identifiers a bare GitHub webhook has no way to supply without a
much larger configuration surface (which replay run is "baseline",
which is "candidate" for this specific commit) that would risk
fabricating a relationship that isn't actually there. `RiskService.
run_assessment` already supports a `compatibility_scan_id`-only call
(added in Phase 11), so this is a supported, non-fabricated use of the
existing risk engine, not a workaround. A PR check can still reach WARN/
BLOCK purely from compatibility-derived risk rules; replay/differential-
sourced risk signal is out of scope until a future phase defines how a
webhook maps to specific replay runs.

## ADR-058 — GitHub Checks credential: `GitHubCredentialProvider` Protocol + `StaticGitHubCredentialProvider`, not a full GitHub App JWT/installation-token exchange (2026-09-14)

A true GitHub App installation-token flow requires signing a JWT with
RS256, which needs a crypto library (`pyjwt`/`cryptography`) — not
installable in this sandbox (same PyPI restriction documented for every
phase, see `app/auth/jwt.py`'s hand-rolled HS256). Rather than block
Phase 12 on that, `app/github/checks_models.py` defines a
`GitHubCredentialProvider` Protocol (`async def get_token() -> str`),
and `app/github/checks_client.py` ships `StaticGitHubCredentialProvider`
(reads `Settings.github_checks_token`) as the production implementation
for now. `HttpxGitHubChecksClient` depends only on the Protocol, so a
real RS256-based JWT-then-installation-token exchange can implement the
same Protocol later with zero changes to any caller or test double
(`FakeGitHubChecksClient` already satisfies `GitHubChecksClient`
directly, independent of credentials entirely).

## ADR-057 — Per-category score caps as the double-counting policy; hard-block rules always carry `score_delta = 0` (2026-09-14)

Spec §16 requires "a clear policy" against over-penalizing the same
underlying evidence. Chosen approach: group the 8 score rules into 5
categories (`compatibility`/`replay`/`differential`/`blast_radius`/
`latency`), sum each category's raw triggered deltas, then clamp each
category's *sum* to a fixed cap (40/45/50/20/15) before adding to the
overall score (also capped at 100). This was preferred over evidence-
key deduplication (harder to define a stable "same evidence" key across
rules with genuinely different predicates) and over a single global
rule-count cap (would suppress legitimately independent categories,
e.g. a moderate compatibility break plus a large blast radius). The two
hard-block rules (`HARD_BLOCK_CRITICAL_COMPAT_BREAK`, `HARD_BLOCK_NEW_
REPLAY_FAILURE`) always report `score_delta = 0` — they influence
`decision` directly, never the numeric score, so `hard_block=true`
never silently inflates `score` past what the ungated rules alone
produced. This is also why `HARD_BLOCK_NEW_REPLAY_FAILURE` deliberately
overlaps in predicate with the score rule `NEW_REPLAY_FAILURE`
(`new_failures > 0`): the duplication is intentional, not a bug — the
score stays a meaningful signal even if a human overrides the hard
block, while the decision itself can never be "averaged away" by
unrelated low-scoring evidence.

## ADR-056 — Decision bands adopted as specified (PASS<30/WARN 30-69/BLOCK≥70); blast radius is `Optional[int]`, never coerced to 0 (2026-09-14)

The spec's own recommended thresholds were adopted as-is (spec §6) —
no data-driven reason surfaced during this phase to deviate, and a
versioned, documented default is more valuable than an unjustified
tweak. `RiskContext.blast_radius_total_affected` is `int | None`, not
`int` defaulting to 0: `RiskService._compute_blast_radius` returns
`None` whenever `BlastRadiusService.compute()` raises
`GraphUnavailable` or `GraphComponentNotFound` (Neo4j unreachable, or
the compatibility scan's component was never synced into the graph),
and `HIGH_BLAST_RADIUS` (`app/risk/rules.py`) treats `None` as "no
signal" — it does not fire. Coercing an unavailable graph to `0` would
read as "checked, nothing affected," which is a fabricated finding; the
engine would rather under-score (never fabricate) than over-claim
certainty about blast radius it couldn't actually compute.

## ADR-055 — Idempotency key: `(project_id, baseline_replay_id, candidate_replay_id, analyzer_version)`, not a client-supplied key (2026-09-14)

Unlike Phase 6/7's `external_run_id`/`idempotency_key` (client-supplied,
for retry-safety across network failures), Phase 10 spec §19 asks for
idempotency across *logical* comparisons — the same baseline/candidate
pair should never produce two reports at the same analyzer version.
`differential_reports`' unique constraint is on the four columns that
together define "the same comparison," enforced at the database level
(migration 0008) and checked first in `DifferentialService.run_analysis`
before any comparison work runs. Including `analyzer_version` in the key
means a future ruleset version *can* re-analyze the same pair and get a
new report — deliberately, since spec §20 requires old reports to never
silently change meaning when rules evolve.

## ADR-054 — Step alignment fallback hierarchy is deterministic, never fuzzy (2026-09-14)

Spec §7 forbids LLM-based step matching and specifies an exact fallback
order. `app/differential/alignment.py` implements it as four sequential
passes over an ever-shrinking "remaining" set — `source_event_id` exact
match, then `sequence_number` exact match, then `component_id` paired
in ascending sequence order (first-available, never best-effort/fuzzy),
then whatever's left is unmatched. Each pass only considers steps
neither side has already matched, so a step is claimed by the first
rule that can match it, never a "best" match by some fuzzy score — this
keeps the same two inputs always producing the same alignment, provable
by `tests/test_differential_alignment.py`'s determinism test.

## ADR-053 — Recursive value diff is a new module, not a repurposed Phase 5 schema diff (2026-09-14)

Spec §11 says "reuse Phase 5 schema-diff utilities where appropriate."
`app/compatibility/diff.py`'s `diff_schemas()` is JSON-Schema-shape-
aware (expects `type`/`properties`/`required`/`enum` keys) — appropriate
for comparing two schema *definitions*, not two arbitrary output
*values* (a tool's actual JSON response, which has no `type`/
`properties` structure of its own). Repurposing it would mean treating
ordinary data fields as schema keywords, producing nonsense diffs.
`app/differential/value_diff.py` is a new, purpose-built recursive
dict/list/scalar comparison instead — but it does reuse Phase 5's
`_MAX_DEPTH` recursion-guard pattern and Phase 6's `app.trajectory.
redaction` sensitive-key set, rather than duplicating either.

## ADR-052 — No decision field exists in `ExplanationResponse`; the LLM/deterministic boundary is structural (2026-09-14)

Spec §10 mandates the LLM output schema must not contain
`risk_score`/`pass`/`warn`/`block`/`compatibility_status`/
`final_decision`. Rather than relying only on a prompt instruction (spec
§11, which is also present, as defense in depth) or on API-layer
filtering, `app/llm/models.py`'s `ExplanationResponse` dataclass simply
has no such field — there is nowhere in the type for a decision to be
put, so no downstream code can accidentally read one back out even if a
future provider tried to add one. `tests/
test_llm_architectural_invariant.py` additionally proves via AST
inspection that no deterministic package (`compatibility`, `graph`,
`replay`, `trajectory`, `domain`) imports `openai` at all, and that the
`openai` package name appears nowhere outside `app/providers/
openai_provider.py`.

## ADR-051 — Bounded evidence, not LLM-chosen evidence (2026-09-14)

Spec §13 forbids letting the model decide what evidence to discard.
`app/llm/bounding.py`'s `bound_evidence()` is a pure function applied
*before* an `ExplanationRequest` is ever constructed: fixed max item
count (25) and per-field character clips, order-preserving (callers are
expected to pre-sort by importance). Truncation is recorded on the
request (`truncated: bool`) and surfaced back in the response's
`limitations` — the model is told evidence was cut, never asked to
choose what to cut.

## ADR-050 — `LLMProvider` as a `typing.Protocol`; OpenAI import confined to one module (2026-09-14)

Spec §4/§17 requires the core application to depend on an abstraction,
not the OpenAI SDK directly, and requires the architecture to stay
extensible to a future provider without a rewrite. A `Protocol`
(structural typing, no explicit inheritance required) rather than an
ABC — `FakeLLMProvider` (tests) and `OpenAIProvider` both satisfy it
just by having a matching `explain()` coroutine. The `openai` package is
imported nowhere except `app/providers/openai_provider.py` (lazily,
inside `explain()`, so the rest of the app never needs `openai`
installed just to start) — enforced by an AST-walking test, not just
convention. No Gemini branch exists in `app/api/deps/llm.py`'s factory
(Phase 9 is skipped per this phase's explicit instruction), but adding
one later is a new class + one new `if`, not a change to
`ExplanationService` or any route.

## ADR-042 — Cross-tenant denial is 404; in-tenant permission denial is 403 (2026-09-14)

**Context:** Security Phase C spec §7/§19 requires deciding, consistently,
whether accessing another organization's resource returns 403 or 404, and
warns against leaking "whether a foreign-tenant UUID exists."

**Decision:** Two different HTTP statuses for two different situations,
both raised by `AuthorizationService` (`app/authz/service.py`):
`OrganizationAccessDenied`/`ProjectAccessDenied` (no membership at all in
the resource's organization) map to **404**, deliberately identical to
`ProjectNotFound` — a caller with no relationship to a tenant cannot tell
whether the UUID they guessed belongs to a real project in another
organization or doesn't exist at all. `PermissionDenied` (a verified
member of the resource's organization, but their role lacks the specific
permission) maps to **403** — the caller already knows this
organization/project exists and that they belong to it, so naming the
real reason (insufficient permission) doesn't leak any tenant-boundary
information a 404 would otherwise hide. Applied consistently everywhere
`AuthorizationService` is used — no route special-cases this.

## ADR-041 — ADMIN gets no `MEMBERSHIP_MANAGE`, not a partial grant (2026-09-14)

**Context:** Security Phase C spec §3 lists `MEMBERSHIP_MANAGE`-equivalent
capabilities only under OWNER; separately, spec §16 says "ADMIN may be
restricted from changing OWNER membership or ownership-sensitive
settings," which could be read as ADMIN having *some* membership
capability short of touching OWNER rows.

**Decision:** `ROLE_PERMISSIONS["admin"]` (`app/authz/permissions.py`)
excludes `MEMBERSHIP_MANAGE` entirely — ADMIN has no membership-mutation
capability at all, not a scoped-down one. This is a strict reading of
§3's base policy (which never grants ADMIN any membership action) and
trivially satisfies §16's "restricted from OWNER-sensitive changes"
(fully restricted is still restricted), without inventing a second,
partial permission tier this codebase would then need to test and
maintain. `app/authz/membership.py`'s `authorize_role_change` is the
decision function a future membership-mutation route would call; no
such route exists yet (documented as future work: `PATCH /organizations/
{organization_id}/members/{user_id}`), so this is tested at the pure-
function level (`tests/test_authz_membership.py`) rather than via HTTP.
The same function also blocks demoting/removing an organization's last
OWNER, closing the "org left with no one who can manage membership"
failure mode.

## ADR-040 — Zero/multiple org memberships yield `organization_id=None`, never an automatic pick (2026-09-14)

**Context:** Security Phase B spec §10: a GitHub-authenticated user may
have zero or several `OrganizationMember` rows. "Do not silently grant
ADMIN/OWNER privileges. Do not automatically add a new user to an
arbitrary existing organization... Security takes priority over
convenience."

**Decision:** `GitHubOAuthService.handle_callback` attaches an
`organization_id`/`role` to the issued JWT only when the user has
*exactly one* membership. Zero memberships -> `organization_id=None`,
`requires_onboarding=True` in the callback response. Multiple
memberships -> also `organization_id=None` (ambiguous — picking one
automatically would be an undocumented, arbitrary privilege choice),
`requires_onboarding=False`. In both `None` cases, authentication still
succeeds and an AgentABI JWT is still issued: login (proving who you
are) is not blocked on org resolution, but the token carries zero
organization-scoped privilege until a later phase's org-selection/
onboarding flow runs. This mirrors ADR-038's existing "role may be
`None`" design rather than inventing a second mechanism.

## ADR-039 — OAuth `state` failures collapse to one error, like `InvalidToken` (2026-09-14)

**Context:** Security Phase B spec §14 lists "invalid/expired/reused
OAuth state" as separate cases to handle securely, and §16 asks for unit
tests distinguishing missing/malformed/expired/reused/mismatched state.

**Decision:** All of these are tested distinctly at the `OAuthStateStore`
contract level (`tests/test_oauth_state.py` — 8 pure tests covering
each case), but `GitHubOAuthService.handle_callback` raises a single
`OAuthStateInvalid` for any `consume()` failure, regardless of reason.
This mirrors `InvalidToken`'s precedent (ADR before this log's Phase A
entries): telling a caller *which* state-validation reason applied
would help an attacker distinguish "this state never existed" from
"this state existed but expired" from "this state was already used" —
information a CSRF-protection mechanism should not leak. `Redis`'s
`GETDEL` cannot reliably distinguish "expired" from "already consumed"
from "never existed" after the fact regardless (all three look
identical: key not present), so a uniform error is also the only
consistent behavior across `RedisOAuthStateStore` and
`InMemoryOAuthStateStore`.

## ADR-038 — Role is a JWT-absent, per-request database lookup, not an embedded claim (2026-09-14)

**Context:** Security Phase A's spec explicitly asks: "Document whether
role is embedded in JWT or reloaded from the database on requests.
Prefer security/correctness over convenience."

**Decision:** `JWTClaims` (`app/auth/claims.py`) carries no role/scope
claim at all — only `sub`, `iss`, `aud`, `iat`, `exp`, and an optional
`org_id` naming the organization the token was issued for.
`get_current_user` (`app/api/deps/auth.py`) always re-queries
`OrganizationMember` for `(user_id, org_id)` on every request to
determine the current role.

**Why:** an embedded role claim goes stale the instant a user is
promoted/demoted/removed after token issuance — a still-valid JWT would
keep granting the old permission until it expires (up to
`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`). Reloading per request costs one
indexed lookup and closes that window entirely: a permission change
takes effect on the very next request. No refresh-token/revocation
infrastructure is needed to compensate, since there's nothing
permission-bearing to revoke inside the token itself.

## ADR-037 — Stdlib-only HS256 JWT implementation; existing OrganizationRole kept as-is (2026-09-14)

**Context:** Two judgment calls this phase, both driven by the same
constraint (this sandbox cannot install packages — PyPI returns 403,
same as every prior phase's ADR-005/006/008/...): (1) no JWT library
(PyJWT/authlib) is installable; (2) the phase's request named
`ADMIN`/`ENGINEER`/`VIEWER` as required roles, but Phase 2 already
shipped `OrganizationRole` as `OWNER`/`ADMIN`/`MEMBER`.

**Decision (JWT):** `app/auth/jwt.py` implements RFC 7519/7515 HS256
JWS compact serialization directly from `hmac`/`hashlib`/`base64`/
`json` — no external dependency. This isn't just a workaround: it
mirrors the codebase's existing pure-module pattern
(`app/compatibility/`, `app/trajectory/`, `app/replay/`), keeping
authentication's core logic dependency-free and genuinely
`pytest`-executable in this environment. The implementation fixes the
algorithm to HS256 everywhere (never reads `alg` from the token to
decide how to verify), closing the "alg: none"/algorithm-confusion
attack class by construction, and uses `hmac.compare_digest` for
constant-time signature comparison. Once dependencies are installable,
swapping to PyJWT/authlib behind this same `encode_token`/`decode_token`
interface is a contained, optional follow-up — not required for
correctness today.

**Decision (roles):** kept `OrganizationRole.OWNER`/`ADMIN`/`MEMBER`
as-is rather than renaming to `ADMIN`/`ENGINEER`/`VIEWER`. The enum is
already migrated (`0001_initial_schema.py`) and used by existing rows;
renaming its values now would be a breaking schema change for no
functional gain — every actual Phase A requirement (role scoped to an
organization membership, not a global field on `User`; a user in
multiple organizations) was already satisfied. This is "reuse, don't
duplicate" applied literally: the spec's own instruction to preserve
Phase 2 models when they already implement the requirement.

## ADR-036 — Phase 7 verification: pure planner/executor logic ran for real; persistence was verified by direct DDL (2026-09-14)

**Context:** Same sandbox restriction as every prior phase — SQLAlchemy/
FastAPI/httpx cannot be installed.

**What ran for real:** `app/replay/` has no SQLAlchemy/Pydantic/FastAPI
import, so `pytest --noconftest` ran 3 pure test files for real — 25/25
passed, combined with Phase 5/6's 124, 149/149. `ruff format`/`ruff
check` clean; `python3.12 -m py_compile` clean; `mypy app` fails on the
same pre-existing `pydantic.mypy` error as every prior phase.

**What was verified instead (ADR-008 pattern):** migration 0005 applied
via raw SQL to a fresh local Postgres 16 (this session's container does
not persist database state — schema re-transcribed from scratch, same
as Phase 6). Directly exercised: the spec's 7-step checkout acceptance
plan persisted in deterministic sequence order with the substituted step
referencing candidate v6 while the original `trajectory_events` row
stayed at baseline v5; the `replay_steps` immutability trigger rejecting
an `UPDATE`; `replay_runs` accepting a legitimate status `UPDATE` (no
trigger); the `(replay_run_id, sequence_number)` unique constraint; the
partial `(project_id, idempotency_key)` index (same-project duplicate
rejected, cross-project reuse allowed); and cascade delete from
`trajectories`.

**What could not be verified:** `test_replay_service.py` (10 tests) and
`test_replays_api.py` (9 tests) need SQLAlchemy/FastAPI/httpx — not
exercised this session.

**Action for the user:** run `make install && make lint && make
typecheck && make test && alembic upgrade head` locally.

## ADR-035 — Idempotency-key retries for replay creation, reusing the ADR-029 pattern exactly (2026-09-14)

**Context:** Replay creation, like trajectory start (Phase 6), is
instrumentation-triggered and may be retried.

**Decision:** `ReplayRun.idempotency_key`, unique per project via a
partial index (`WHERE idempotency_key IS NOT NULL`), same "exact match
returns existing, conflict rejects" shape as ADR-029's
`external_run_id`/`external_event_id` handling — no new idempotency
concept invented for this phase, just the same one applied to a third
resource.

## ADR-034 — A structured execution failure is normal evidence; an executor raising is a domain error (2026-09-14)

**Context:** Phase 7 must never silently fall back to historical output
after a required candidate execution fails, but also must not treat
every failure as an exceptional server error.

**Decision:** `ExecutionOutcome(status="failed", ...)` — the candidate
ran and failed — is recorded as a normal `ReplayStep` with
`status=FAILED`; the replay run transitions to `FAILED` and execution
stops (no further steps, no fallback to baseline output). An executor
that *raises* instead of returning a structured outcome (a transport or
programming error) is different: caught, the run is transitioned to
`FAILED` first so state stays consistent, then re-raised as
`ReplayExecutionFailed` (HTTP 422) — distinguishing "the candidate
failed" (expected, informative) from "the execution machinery itself
broke" (unexpected).

## ADR-033 — Replay evidence: insert steps once, already finalized, never insert-then-update (2026-09-14)

**Context:** `replay_steps` needs the same unconditional immutability
trigger Phase 6 gave `trajectory_events` (ADR-027), but a naive design
(`INSERT` a `PENDING` step, later `UPDATE` it to `EXECUTED`) would
directly contradict an unconditional "reject every `UPDATE`" trigger.

**Decision:** `ReplayRun.plan` (JSONB) is computed once by
`app/replay/planner.py` at creation and stored on the mutable
`replay_runs` row (which has no trigger, mirroring `trajectories`).
`execute_replay()` walks that stored plan and calls `INSERT` on
`replay_steps` exactly once per step, only after that step's outcome
(reused/skipped/provider-required, or an executor's actual result) is
already known — never before. This keeps `replay_steps` a pure
append-only evidence table, consistent with every other append-only
table in this codebase (Phase 5's scan evidence, Phase 6's
`trajectory_events`), instead of carving out a special "mutable during
execution" exception for it.

## ADR-032 — Phase 6 verification: pure trajectory logic ran for real; persistence/API were verified by direct DDL, not through `pytest` (2026-09-13)

**Context:** Same sandbox restriction as every prior phase (ADR-005/006/
008/013/021/022) — PyPI, apt, and Docker-registry pulls all return 403 in
this container, so `fastapi`/`sqlalchemy`/`pydantic`/`httpx` cannot be
installed.

**What ran for real:** `app/trajectory/` has no SQLAlchemy/Pydantic/
FastAPI import anywhere in its graph, so `pytest --noconftest` (the same
workaround established in Phase 5) executed the real, already-installed
`pytest` binary against six pure test files — 49/49 passed, combined with
Phase 5's 75, 124/124. `ruff format`/`ruff check` clean;
`python3.12 -m py_compile` clean on every file; `mypy app` fails on the
same pre-existing `pydantic.mypy` import error as every prior phase.

**What was verified instead, following the ADR-008 pattern:** migration
0004 applied via raw SQL to a real local Postgres 16 (freshly started
this session — the container's Postgres does not persist state across
sessions, so migrations 0001-0004 were re-transcribed and reapplied from
scratch). Directly exercised: the spec's exact 8-event
`checkout-run-8291` acceptance trajectory (simulating the app's atomic
sequence-allocation UPDATE per event) producing the correct 1-8 ordering
and event types; the `trajectory_events` immutability trigger rejecting
an `UPDATE`; the `trajectories` row accepting a legitimate `UPDATE` (no
trigger, by design — ADR-027); the `(trajectory_id, sequence_number)`
unique constraint rejecting a duplicate; the partial
`(project_id, external_run_id)` unique index rejecting a same-project
duplicate while allowing the same id in a different project; and
`ON DELETE CASCADE` from `projects` removing a trajectory and its events.

**What could not be verified:** `test_trajectory_recorder_service.py` (24
tests) and `test_trajectories_api.py` (16 tests) are written and
`py_compile`-clean but need SQLAlchemy/FastAPI/httpx to run through
`pytest` itself — not exercised this session. Same caveat as ADR-022:
the raw-SQL verification above exercises the same schema and constraints
these tests assert against, but not the Python service/API code paths
themselves.

**Action for the user:** run `make install && make lint && make
typecheck && make test && alembic upgrade head` locally to complete
verification.

## ADR-031 — Phase 5 `conftest.py` immutability-trigger gap: found and fixed this session (2026-09-13)

**Context:** While extending `tests/conftest.py`'s `_IMMUTABILITY_DDL`
fixture for Phase 6's `trajectory_events` trigger, it became clear the
fixture had never been extended for Phase 5's
`prevent_compatibility_evidence_mutation()` trigger either. Because
SQLAlchemy has never been installable in this sandbox in any phase,
`test_compatibility_service.py`'s two immutability tests
(`test_scan_row_is_immutable_at_the_database_level`,
`test_scan_change_row_is_immutable_at_the_database_level`) have never
actually executed — `Base.metadata.create_all()` creates tables from ORM
metadata only, not raw-SQL triggers, so those two tests would have
silently failed the moment they could run, for a reason unrelated to the
compatibility engine itself.

**Decision:** Fix the fixture now rather than leave a known gap in place.
`_IMMUTABILITY_DDL` was extended to include all three trigger sets to
date (Phase 3's `component_versions` trigger, Phase 5's two
`compatibility_scans`/`scan_changes` triggers, Phase 6's
`trajectory_events` trigger), each guarded with `DROP TRIGGER IF EXISTS`
so the fixture stays idempotent across repeated test runs. This is a
test-infrastructure correction, not a redo of Phase 5's implementation —
no production code changed, and the fix is purely additive.

**Consequence:** once SQLAlchemy/asyncpg become installable, Phase 5's
immutability tests will pass for the first time rather than failing on
an infrastructure gap unrelated to their actual assertions.

## ADR-030 — Redaction and payload-size limits are foundations, not a DLP platform; S3 archival deferred (2026-09-13)

**Context:** The spec explicitly warns against building "a complete DLP
platform" and against introducing S3 archival in this phase, while still
requiring practical redaction and payload-size safeguards.

**Decision:** `redaction.sanitize()` matches against a small, fixed,
documented set of sensitive keys (`password`, `secret`, `token`,
`api_key`, `authorization`, `access_token`, `refresh_token`),
case-insensitively and with hyphens normalized to underscores, recursing
through nested dicts/lists/tuples and replacing matched values with a
constant placeholder (`"***REDACTED***"`) — deterministic and auditable,
not a heuristic scanner for arbitrary secret-shaped strings.
`payload_limits.enforce_payload_limit()` is a two-tier soft/hard byte
limit (32KB / 1MB, both overridable) using the same canonicalized-JSON
size measurement as Phase 3's checksum: under the soft limit, store in
full; between soft and hard, store a deterministic truncated
representation (`_truncated`, `_original_size_bytes`, a bounded
`_preview`) instead of the real payload; over the hard limit, reject the
event outright (`TrajectoryPayloadTooLarge`). Redaction always runs
before size enforcement.

**What's deliberately deferred:** archiving oversized or historical
payloads to S3/object storage with a database pointer. Today, a payload
that would exceed the hard limit is rejected rather than archived
externally. This is an explicit, documented limitation, not an oversight
— extending it later means adding an archival backend and a
`payload_ref`-style column, without changing the redaction/size-check
call sites that already exist.

## ADR-029 — Dual idempotency: `external_run_id` for trajectory start, `external_event_id` + content hash for event append (2026-09-13)

**Context:** Instrumentation code retries. A trajectory-start call or an
event-append call might be sent twice — after a network timeout, a
process restart, or an at-least-once delivery guarantee upstream — and
must not silently create a duplicate trajectory or a duplicate event.

**Decision:** Two independent idempotency keys, one per operation, both
using the same "exact match returns existing, conflict rejects
deterministically" shape. Trajectory start: a partial unique index on
`(project_id, external_run_id) WHERE external_run_id IS NOT NULL`;
`start_trajectory()` catches the resulting `IntegrityError`, re-fetches
the existing row, and compares identifying fields
(`workflow_component_id`, `workflow_version_id`, `environment`) — an
exact match returns the existing trajectory, any difference raises
`TrajectoryAlreadyExists`. Event append: a partial unique index on
`(trajectory_id, external_event_id) WHERE external_event_id IS NOT
NULL`; instead of re-comparing raw fields, `append_event()` uses the
event's own `content_hash` (ADR-028) as the equality check — an
exact-hash retry returns the existing event with **no new row and no
sequence number consumed**; a hash mismatch (same id, different data)
raises `DuplicateTrajectoryEvent`. Reusing the hash avoids inventing a
second, potentially inconsistent notion of "same event."

**Consequence:** retried instrumentation calls are safe by construction;
callers that need idempotency simply supply a stable `external_run_id`/
`external_event_id`, and callers that don't care can omit them entirely
(both columns are nullable, both indexes are partial).

## ADR-028 — Event integrity hash: SHA-256 over replay-relevant fields only, reusing Phase 3's canonicalization (2026-09-13)

**Context:** The spec asks for a deterministic integrity hash "if it
doesn't materially complicate Phase 6," and separately needs *some*
mechanism to distinguish an exact-duplicate event retry from a
conflicting reuse of the same `external_event_id`.

**Decision:** `hashing.compute_event_hash()` builds a single dict from
exactly the fields that matter for replay and evidentiary integrity —
`trajectory_id`, `sequence_number`, `event_type`, `component_version_id`,
and the (already redacted and size-limited) `input`/`output`/`error`
payloads — and reuses Phase 3's `canonicalize_content()` (sorted keys,
compact separators) plus SHA-256, rather than inventing new hashing
logic. The hash is computed once at append time and stored on the event
row; it doubles as the comparison mechanism for `external_event_id`
idempotency (ADR-029), so no second hashing scheme was needed.

**Scope decision:** the hash deliberately excludes `recorded_at`
(ingestion time, not semantically meaningful for replay) and metadata
fields that don't affect what happened — only what a replay engine would
actually need to reproduce or verify is covered.

## ADR-027 — `trajectories` has no immutability trigger; `trajectory_events` does (2026-09-13)

**Context:** Phase 3 (`component_versions`, ADR-011) and Phase 5
(`compatibility_scans`/`scan_changes`, ADR-024) both used unconditional
`BEFORE UPDATE` triggers to enforce immutability at the database level.
Phase 6 has two tables and they are not symmetric: a trajectory event
never changes once recorded, but a trajectory's `status`, `completed_at`,
`error`, and `next_sequence` are expected to change over its `RUNNING`
lifetime.

**Decision:** `trajectory_events` gets the same unconditional
`prevent_trajectory_event_mutation()` trigger shape as Phase 5's
evidence tables — any `UPDATE` is rejected outright. `trajectories` gets
**no trigger at all**, mirroring Phase 3's `components` identity table
(mutable) rather than `component_versions` (immutable): the row's
lifecycle-relevant columns are genuinely expected to mutate, and trying
to allow-list "these four columns may change, nothing else" at the
trigger level would just reimplement the service layer's own status
machine in PL/pgSQL. Instead, the service layer is the sole place that
can `UPDATE` a `Trajectory` row (`allocate_sequence()`,
`transition_status()`), and both do so via narrow, atomic, conditional
statements — never a general-purpose update path.

**Consequence:** the append-only guarantee that actually matters for
audit/replay (event history) is enforced at the strongest layer
(database trigger, cannot be bypassed by any code path), while the
mutable-by-design row (trajectory status) is governed by service-layer
discipline, consistent with how Phase 3 already treats its own
mutable-vs-immutable table pair.

## ADR-026 — Concurrency-safe sequence allocation: one atomic conditional `UPDATE`, not `SELECT max()+1` (2026-09-13)

**Context:** The spec is explicit that ordering must rely on a
trajectory-local monotonic `sequence_number`, not timestamps, and that
two concurrent appenders must never receive the same sequence number or
silently corrupt ordering. It calls out "`read max(sequence) + 1` without
synchronization" by name as the anti-pattern to avoid.

**Decision:** Each trajectory row carries its own `next_sequence`
counter. `TrajectoryRepository.allocate_sequence()` issues a single
statement:

```sql
UPDATE trajectories
   SET next_sequence = next_sequence + 1
 WHERE id = :id AND status = 'running'
RETURNING next_sequence;
```

Postgres takes a row-level lock for the duration of an `UPDATE`, so
concurrent callers targeting the same trajectory are serialized by the
database itself — there is no read-then-write window for two callers to
observe the same value. Folding `WHERE status = 'running'` into the same
statement closes a second race: a trajectory that transitions to
`COMPLETED`/`FAILED` between an appender's "is this trajectory still
running" check and its sequence allocation cannot silently receive a
post-terminal event, because the conditional `UPDATE` simply matches zero
rows (`allocate_sequence()` returns `None`, and the service raises
`TrajectoryTerminal`) instead of two separate statements racing each
other.

**Verified:** a real `asyncio.gather` test
(`test_concurrent_appends_allocate_distinct_sequence_numbers`) drives 8
independent `AsyncSession`/`TrajectoryRecorderService` instances against
the same trajectory concurrently and asserts the resulting sequence
numbers are exactly `{1..8}` with no duplicates; the same guarantee was
also exercised directly against real Postgres via raw SQL this session
(see ADR-032).

## ADR-025 — Generic `diff_mapping()` fallback for component types Phase 3 didn't fully structure (2026-09-13)

**Context:** The Phase 5 spec asks for Workflow (steps/ordering), Policy
(rule/capability changes), MCP-server, and API comparison, but Phase 3's
`app/domain/component_content.py` models `WorkflowContent.definition` and
`PolicyContent.rules` as unstructured `dict`s, and `MCPServerContent`/
`APIContent` carry no schema field at all. Inventing structure the
registry doesn't actually have would be dishonest determinism — it would
look like real analysis of a contract that isn't there.

**Decision:** `app/compatibility/diff.py`'s `diff_mapping()` is a single,
generic, non-directional recursive dict differ (config field
added/removed/changed), reused by five of `analyzer.py`'s per-type
functions as their fallback path. For Workflow specifically,
`_diff_agent_tools`-style convention detection is attempted first — *if*
`definition` looks like `{"steps": [{"id"|"name", "required", ...}]}`,
step add/remove/reorder/required-removal is reported with real
`ChangeType`s; otherwise it falls back to `diff_mapping()` on the whole
`definition`. Policy, MCP-server config fields, and API's `auth`/`base_url`
go straight to `diff_mapping()`. This is a deliberate, documented scope
decision tied to what Phase 3 actually modeled, not a shortcut avoiding
real diffing — extending it just means giving these `ComponentType`s
richer `*Content` models later, at which point the same `diff_schemas()`
machinery already handles them for free.

## ADR-024 — Compatibility scan persistence: plain-VARCHAR `change_type`, unconditional immutability trigger, always-new-scan idempotency, same-component rule enforced twice (2026-09-13)

**`change_type` as `String(100)`, not a native Postgres enum:** unlike
`classification`/`severity`/`status`, which are small closed 3/5/3-member
sets, `ChangeType` already has ~40 members and is exactly the kind of
thing later phases (behavioral differential analysis, new schema-diff
rules) will keep extending. A native enum requires an `ALTER TYPE ... ADD
VALUE` migration per new member; a plain indexed `VARCHAR` makes adding a
change type a Python-only change to `app/compatibility/models.py`.

**Immutability trigger is unconditional, not column-scoped:** Phase 3's
`prevent_component_version_mutation()` (ADR-011) only blocks
`content`/`checksum` changes, deliberately allowing `metadata` updates.
Phase 5's `prevent_compatibility_evidence_mutation()` rejects *any* UPDATE
on `compatibility_scans`/`scan_changes` unconditionally, because — unlike
a component version, which has one genuinely mutable field — no column on
either compatibility table has a legitimate reason to change after the
scan completes; the whole row is the evidence.

**Idempotency: `run_scan` always creates a new historical row.** Two
`run_scan(project, component, "1", "2")` calls produce two distinct
`CompatibilityScan` rows, never a dedup/reuse of an existing one (proved
by `test_repeated_scans_create_separate_historical_rows`). Chosen
deliberately, not left as an accidental side effect of the lack of a
uniqueness constraint: a scan is an audit record of "this comparison ran
at this time," and later phases (replay evidence, release-risk decisions,
GitHub check-runs) need to attach to *the specific run that gated a
specific deployment*, not to "the latest scan of this pair." Re-running
is cheap (pure computation, no external calls) so there's no cost to
always recording history.

**Same-component rule enforced both structurally and defensively:** the
public `run_scan(project_id, component_id, baseline_version,
candidate_version)` signature takes one `component_id` for both version
lookups, so comparing two different components is unreachable through the
real API by construction. `_scan_from_versions` *additionally* asserts
`baseline.component_id == candidate.component_id` at runtime and raises
`InvalidCompatibilityComparison` if it ever isn't — independently
unit-tested by calling that private method directly with mismatched
components (`test_scan_from_versions_rejects_unrelated_components`). Two
enforcement layers because "structurally unreachable today" and "will
always stay unreachable as this code evolves" are different guarantees.

## ADR-023 — Directional compatibility classification, and reserving `CRITICAL` for one specific case (2026-09-13)

**Context:** The same structural change (e.g. "field removed") means
different things depending on whether the schema is something callers
send (input/request) or something callers receive (output/response).

**Decision:** `Direction` (`INPUT`/`OUTPUT`/`NEUTRAL`) is an explicit
parameter threaded through `diff_schemas()`/`classify()`, never inferred
from field names or component type. `analyzer.py` passes `INPUT` for a
tool/API's `input_schema`, `OUTPUT` for `output_schema`, and `NEUTRAL` for
a standalone `SCHEMA` component whose usage isn't known. The rules table
(`app/compatibility/rules.py`) encodes the asymmetry directly: adding a
required input field is breaking (new callers must supply it — existing
callers can't), removing a required input field is compatible (existing
callers already satisfy the stricter old contract); the reverse holds for
output — removing an output field is breaking (existing consumers may
read it), adding one is compatible. `NEUTRAL` is defined to never be more
lenient than the stricter of `INPUT`/`OUTPUT` for the same change type
(tested directly: `test_neutral_direction_is_never_more_lenient_than_
either_known_direction`), since with no known direction the safe
assumption is the more conservative one.

**`Severity.CRITICAL` is reserved for exactly one case:**
`(REQUIRED_FIELD_ADDED, Direction.INPUT)`. Every other breaking change is
at most `HIGH`. This is the one case the engine can assert with
*certainty*, not likelihood — any existing caller not already sending the
new required field is guaranteed to fail schema validation. Every other
breaking classification (type changes, enum narrowing, output field
removal) depends on how a specific consumer actually uses the data, which
Phase 5 explicitly cannot determine (that's replay/behavioral-diff work,
Phases 7/10) — so those stay `HIGH` rather than being inflated to
`CRITICAL`.

## ADR-022 — Phase 5 verification: the deterministic engine ran for real; persistence was verified by direct DDL, not through `pytest` (2026-09-13)

**Context:** Same sandbox restriction as every prior phase (ADR-005/006/
008/013/021) — `fastapi`/`sqlalchemy`/`pydantic`/`httpx`/`alembic` cannot
be installed here (PyPI returns 403), so the project's own `pytest` suite
cannot run end-to-end.

**What is materially better this phase:** the entire compatibility engine
(`app/compatibility/{models,schema_normalizer,rules,diff,analyzer}.py`) is
plain-dataclass, stdlib-only Python — no SQLAlchemy/Pydantic/FastAPI
import anywhere in that package. That made it possible to bypass
`tests/conftest.py` (which imports `httpx` at collection time) with
`pytest --noconftest` and run the real, installed standalone `pytest`
binary (`/root/.local/bin/pytest`, a `uv tool install`) directly against
`tests/test_schema_normalizer.py`, `test_rules.py`, `test_diff.py`, and
`test_analyzer.py`: **75/75 passed**, including the exact spec §31
acceptance case run through the generic engine (not hardcoded). This is a
strictly stronger verification story than Phase 4's manual `asyncio`
script, because it is the real pytest runner, not a substitute.

**What still could not run through pytest:** `test_compatibility_
service.py` (15 tests) and `test_compatibility_api.py` (11 tests) need the
`session`/`client`/`db_engine` fixtures, which require SQLAlchemy/
FastAPI/httpx — unavailable, so these files are written (and
`python3.12 -m py_compile`-clean) but not pytest-executed this session.

**What was verified instead, following the ADR-008 pattern:** migration
0003's full `upgrade()` was hand-transcribed to raw SQL (types, tables,
indexes, the `prevent_compatibility_evidence_mutation` trigger function
and both triggers) and run directly against a real local Postgres 16
(`agentabi_test`), on top of migrations 0001/0002 transcribed the same
way. Then, with real rows (the spec §31 tool contract: baseline
`{customer_id, amount, currency}` all required → candidate `{user_id,
amount}`), directly exercised: insert/select round-trip of a
`compatibility_scans` + 3 `scan_changes` rows including JSONB
`old_value`/`new_value`; both immutability triggers, each producing the
expected `ERROR: compatibility scan evidence is immutable once created`
on a raw `UPDATE`; the pre-existing unique-slug constraint; and
`ON DELETE CASCADE` from `projects` removing the scan and its changes.
All as expected — proving the DDL and constraints are correct Postgres,
same caveat as ADR-008: the Alembic *tool* itself wasn't exercised, only
the SQL it would produce. The schema was dropped and recreated cleanly
afterward; nothing persists between sessions in this sandbox.

**Action for the user (once run somewhere with normal PyPI access):**
```
cd backend && make install
alembic upgrade head
pytest tests/test_compatibility_service.py tests/test_compatibility_api.py -v
pytest tests/ -v   # full suite
mypy app
```

## ADR-021 — Phase 4 Neo4j/Docker verification gap: genuinely attempted, genuinely unavailable (2026-09-13)

**Context:** The Phase 4 spec explicitly requires a real attempt to run
Neo4j — via Docker or any other means — in both the cloud sandbox and (per
the user's move of the authoritative repo) the Mac, before concluding it
is unavailable, with exact commands documented if it truly isn't. This ADR
records exactly what was tried, in both places, this session.

**Cloud sandbox (`/home/claude/agentabi`):**
- `docker version` succeeds — a Docker daemon (`sudo -n dockerd`, 29.4.3)
  runs in this container, which was *not* true in earlier phases. This is
  new and worth recording.
- `docker pull hello-world` (and, by the same mechanism,
  `docker compose -f docker-compose.yml up -d neo4j`) fails:
  `403 Forbidden` from `registry-1.docker.io` — the same outbound-egress
  allowlist that blocks PyPI (`pypi.org`/`files.pythonhosted.org`) and apt
  (`archive.ubuntu.com`, confirmed 403 again this phase via
  `apt-get install python3-fastapi`) also blocks the Docker Hub registry.
  So: the daemon works, but no image — Neo4j or otherwise — can be pulled.
- No `neo4j`/`cypher-shell` binary exists as a system package, and no
  offline-installable Neo4j distribution (server tarball, `.deb`) is
  reachable for the same network-policy reason. Java 21 is present (in
  case a plain-jar install were possible), but there is nothing to fetch
  to install *with* it.
- No Python package (`neo4j`, or in fact `fastapi`/`sqlalchemy`/anything
  in `pyproject.toml`) could be installed in this container this session
  — `pip install`, `uv pip install -e .`, and the apt fallback all return
  403. This is the same restriction Phases 1–3 hit (ADR-005/006/008/013),
  not a new regression specific to Neo4j.

**Mac Desktop, via the device bridge (`mcp__remote-devices__device_bash`,
which runs in an isolated Linux VM on the user's Mac — explicitly **not**
a shell on macOS itself, so this does not prove anything about the Mac's
own Docker Desktop or Homebrew state):**
- No `docker` binary in that VM.
- Python 3.10 only (Phase 4, like the rest of the backend, targets 3.12
  language features — PEP 695 generics, `enum.StrEnum` usage patterns —
  so even a same-version pip install wouldn't produce a matching runtime).
- `curl` to `pypi.org` returns `403 Forbidden from proxy after CONNECT` —
  the VM's own egress is blocked by the same class of policy.

**Conclusion:** Neo4j could not be run for real, anywhere reachable from
this session, this phase. This is a genuine, actively-attempted gap, not
an assumed one.

**What was verified for real instead, given that constraint:**
- `ruff format --check` / `ruff check` — clean on every Phase 4 file
  (ruff itself is a standalone Rust binary already present at
  `/root/.local/bin/ruff`, so it needed no install).
- `python3.12 -m py_compile` on every new/changed file — clean (proves
  syntax validity under the actual target Python version, even without
  the dependencies installed to run it).
- `mypy` — fails immediately on `pyproject.toml`'s `pydantic.mypy` plugin
  (`No module named 'pydantic'`), identical to every prior phase's
  documented mypy gap; not a new Phase 4-specific failure.
- **The deterministic BFS traversal, cycle handling, tenant isolation, and
  relationship-validation logic — the actual business logic this phase's
  spec cares most about proving — genuinely ran, this session, for real.**
  `pytest` itself could not run (not installed, see above), so this was
  executed as a standalone `asyncio`-driven script
  (`/tmp/verify_phase4_pure_logic.py`, not committed — a manual run, not a
  replacement for the real `pytest` suite) that imports the actual
  `app.services.blast_radius.BlastRadiusService` and
  `app.domain.relationship_rules` modules directly and exercises them
  against `FakeGraphRepository` (`tests/fakes.py`). This was possible at
  all only because `app/graph/repository.py`'s `neo4j` import was made
  lazy (moved under `TYPE_CHECKING`/inside the methods that actually touch
  the driver, not at module level — see its module docstring) specifically
  so the `GraphRepository` Protocol and everything built on it could be
  imported without the `neo4j` package installed. Result: **26/26 checks
  passed**, covering every allowed relationship triple, the
  Model-cannot-call-Workflow rejection, a leaf component's empty blast
  radius, an unsynced-component error, direct vs. transitive dependents
  with correct depth/path values, `max_depth` cutoff, a 3-node cycle
  (A→B→C→A) terminating with no duplicates and the correct 2-member
  result (not 3 — confirming the cycle didn't leak the start node back
  into its own result), cross-tenant isolation, and deterministic ordering
  across repeated calls. This is real execution of real code, not a
  fabricated result — but it is not the same as running the actual
  `tests/test_blast_radius_service.py`/`test_relationship_rules.py` files
  through `pytest` (which additionally need `pytest`/`pytest-asyncio`
  installed, and were written to mirror this exact coverage plus more —
  see ADR-018). `DependencyGraphService`'s tests additionally need
  SQLAlchemy for the real-Postgres `sync_component` integration test, so
  that one genuinely could not be executed this way.
- `tests/test_graph_repository.py` exists specifically to exercise real
  Cypher against a real Neo4j instance, and is written to `pytest.skip()`
  cleanly (not fail, not fake a pass) when Neo4j isn't reachable — see
  its module docstring for the exact commands to run it for real.

**Action for the user (exact commands, once run somewhere with normal
network/Docker access):**
```
docker compose -f docker-compose.yml up -d neo4j
cd backend && make install
pytest tests/test_graph_repository.py -v          # real Cypher, currently skipped
pytest tests/ -v                                   # full suite, including the above
mypy app
```
Until that runs clean, Phase 4's Cypher itself (as opposed to the Python
logic layered on top of it) should be treated as reviewed, not proven.

## ADR-020 — Dependency direction convention: edges point from dependent to dependency (2026-09-13)

**Decision:** Every `DependencyRelationshipType` edge points **from the
component that depends on something, to the thing it depends on** — e.g.
`(Agent)-[:CALLS]->(Tool)`, `(Agent)-[:USES_MODEL]->(Model)`,
`(Workflow)-[:CONTAINS]->(Agent)`. "X's dependencies" = X's outgoing
edges. "X's dependents" (who breaks if X changes — the actual
blast-radius question) = X's **incoming** edges.

**Why this is worth an ADR of its own, not just a docstring:** it is the
single easiest thing to get backwards in this whole phase, and getting it
backwards would silently invert every blast-radius answer (reporting "what
this component depends on" when asked "what depends on this component," or
vice versa) without ever raising an error. `app/graph/repository.py`'s
`_LIST_DEPENDENCIES_QUERY` (follows `-[r]->`) and
`_LIST_DEPENDENTS_QUERY` (follows `<-[r]-`) are the only two Cypher
queries that read in opposite directions, and both carry an inline
comment restating this convention next to the arrow. `BlastRadiusService`
calls only `list_direct_dependents` (incoming edges), never
`list_direct_dependencies`, and this is tested explicitly (see
`test_blast_radius_service.py::test_direct_dependents_only` and
`::test_transitive_dependents_multiple_hops`, which assert the *specific*
components returned, not just a count, so a direction bug would fail
loudly).

**Alternative considered:** edges pointing from dependency to dependent
(`(Tool)-[:CALLED_BY]->(Agent)`) — rejected because relationship names
read more naturally in the "X USES_MODEL Y" / "X CALLS Y" direction that
matches how a developer would say the relationship out loud, at the cost
of "dependents" being the less-intuitive (incoming) direction — a cost
paid once, in this ADR and the code comments, rather than in every
relationship type's name.

## ADR-019 — Tenant isolation enforced directly in Cypher, not only at the application layer (2026-09-13)

**Decision:** Every Cypher query in `app/graph/repository.py` that reads
or writes a node includes `project_id` as a `MATCH` predicate on *every*
node pattern in the query — not just the "entry point" node. E.g.
`_LIST_DEPENDENCIES_QUERY` filters both the source (`{component_id: ...,
project_id: ...}`) and the target (`WHERE target.project_id = $project_id`)
by tenant, and `create_dependency`/`delete_dependency` scope both
`source`/`target` `MATCH` clauses by `project_id`.

**Why not rely on component IDs being UUIDs (globally unique, so
"scoping" is theoretically redundant):** the spec explicitly calls this
out as insufficient, and it's right to: a UUID being globally unique
doesn't stop a Cypher query written without a `project_id` filter from
matching (and returning, or worse, linking) a node that happens to belong
to a different tenant if that node's `component_id` were ever guessed,
logged, or reused across a bug. Scoping every `MATCH` closes that off
structurally — a cross-tenant query has no path to succeed even if the
caller supplies a correct-but-foreign `component_id`, rather than "isn't
expected to happen because IDs don't collide."

**Verified by:** `test_dependency_graph_service.py::
test_tenant_isolation_across_projects` and
`test_blast_radius_service.py::test_tenant_isolation_in_blast_radius`
both create a real edge under `project_a` and assert that querying the
*same* `component_id` under `project_b` raises `GraphComponentNotFound`
rather than leaking the other tenant's data — plus
`test_graph_repository.py::test_get_component_node_is_tenant_scoped`
against real Neo4j (skipped in this session per ADR-021, but written to
run for real once Neo4j is reachable).

## ADR-018 — Blast radius as pure-Python BFS over one-hop repository calls, not a Cypher variable-length path (2026-09-13)

**Decision:** `BlastRadiusService.compute()` is a plain Python
breadth-first search: it calls `GraphRepository.list_direct_dependents()`
one hop at a time, tracks a `visited` set of component IDs, and stops at
`max_depth`. It does **not** issue a single Cypher query like `MATCH
(x)<-[*1..10]-(y) RETURN y`.

**Why:** Three reasons, in order of how much they mattered:
1. **Cycle/dedup/depth-limit control is explicit and independently
   testable.** A Cypher variable-length path *can* be made cycle-safe
   (`apoc.path.subgraphNodes`, or manual dedup in the query), but that
   correctness then lives inside a query string that can only be tested
   against a live database. The BFS's cycle handling
   (`visited.add(component_id)` before a node is enqueued, so a cycle
   simply produces no new work at that node) is ~5 lines of plain Python,
   directly unit-tested via `FakeGraphRepository` — including the
   specific case the spec calls out, a 3-node cycle A→B→C→A
   (`test_blast_radius_service.py::test_cycle_terminates_and_deduplicates`)
   — without needing a real Neo4j instance at all. Given this phase's
   documented Neo4j-unavailability (ADR-021), that testability is not a
   nice-to-have; it is the difference between this algorithm having real
   test coverage and having none.
2. **No LLM, no heuristics, nothing implicit.** The spec is explicit that
   blast radius must be deterministic graph reachability. A hand-written
   BFS makes every step of "how did we decide X is affected" traceable in
   plain Python (and in each `BlastRadiusEntry.path`), rather than trusting
   a query planner's traversal order.
3. **`GraphRepository` stays a narrow, boring interface** (seven single-hop
   methods) instead of growing a bespoke "give me the whole reachable
   subgraph" method whose semantics (depth limit? cycle handling? which
   fields come back?) would have to be re-specified and re-tested per
   backend.

**Tradeoff being made:** N+1-shaped traversal (one query per BFS layer,
not one query for the whole subgraph) — for a project's scale (component
counts, not raw event volume) this is the right trade; if it ever isn't,
the `GraphRepository` Protocol boundary is exactly where a batched Cypher
`list_dependents_multi(ids)` method could be added later without
`BlastRadiusService`'s algorithm changing.

**Alternative considered:** `apoc.path.subgraphAll`/variable-length Cypher
— rejected per the above, and additionally requires the APOC plugin
(already planned for `docker-compose.yml`'s Neo4j service per Phase 1, but
an extra moving part this phase's core logic doesn't need to depend on).

## ADR-017 — Synchronous, service-driven Postgres→Neo4j sync (not event-driven) (2026-09-13)

**Decision:** `DependencyGraphService.sync_component()` is a plain async
method an API caller invokes explicitly (`POST
/projects/{id}/components/{id}/graph/sync`) to push one component's
current Postgres identity into Neo4j. There is no background worker, no
outbox table, no Kafka producer/consumer keeping the two databases
continuously in sync.

**Why:** The spec explicitly scopes Kafka/event-driven processing to
Phase 13, and building an event pipeline now would mean designing it twice
— once without the event bus that Phase 13 actually introduces (topics,
consumer groups, delivery semantics), and once for real. A synchronous
sync call is the honest amount of infrastructure for what Phase 4 alone
needs: a caller (a future API consumer, or Phase 5's compatibility engine)
that has just created/updated a component and wants it reflected in the
graph can call `sync_component` right after, and get a definite
success/failure answer inline rather than an eventually-consistent one.

**Consequence documented, not hidden:** the graph is only ever as fresh as
the last explicit `sync_component` call for a given component — creating
a `ComponentVersion` in Postgres does **not** automatically update the
graph node's `version`/`checksum`. This is intentional scope, not an
oversight: automatic propagation is exactly the kind of "keep two stores
consistent on every write" problem Phase 13's event pipeline exists to
solve properly (outbox pattern, retries, ordering), and doing it
ad hoc here would be building a worse version of that early.

## ADR-016 — Pluggable readiness-check registry (`app/core/readiness.py`) (2026-09-13)

**Decision:** `/api/v1/ready` no longer hardcodes a single `database: bool`
field. `app/core/readiness.py` holds a `READINESS_CHECKS: dict[str,
Callable[[], Awaitable[bool]]]` registry (currently `database` and
`graph`); the endpoint runs every registered check and returns `{"status":
"ok"|"unavailable", "checks": {name: bool, ...}}`, 503 if any check fails.

**Why:** The spec calls for Neo4j readiness to extend, not replace or
special-case, the existing Postgres check, and to be designed so
Redis/Kafka (Phases 13+) can be added the same way. A dict of
zero-argument async callables is the minimum structure that achieves that
— adding a future check is a one-line addition to `READINESS_CHECKS`, not
a change to the endpoint function itself. `/health` (pure liveness) is
deliberately untouched by any of this — it still never calls an external
dependency.

**Breaking change acknowledged:** this changes `ReadinessResponse`'s shape
(`database: bool` → `checks: dict[str, bool]`); `tests/test_health.py` was
updated in the same commit, and this is called out explicitly rather than
silently changing a previously-documented response shape.

## ADR-015 — Graph nodes carry identity only, never the JSONB content payload (2026-09-13)

**Decision:** `ComponentNode` (the dataclass `Neo4jGraphRepository`
reads/writes) mirrors exactly the identity columns already on Postgres's
`components`/`component_versions` tables (`component_id`, `project_id`,
`organization_id`, `component_type`, `name`, `slug`, `version`,
`checksum`, `synced_at`) and nothing else — no `content` JSONB, no
`description`, no `status`.

**Why:** PostgreSQL is, and stays, the single source of truth for a
component's actual configuration/content (per ADR-009's generic
`components`/`component_versions` design). Neo4j's job is answering graph
questions — "what depends on this," "what breaks if this changes" — which
need identity and relationships, not the payload those relationships point
at. Duplicating `content` into Neo4j would mean every future
`ComponentVersion` write has to remember to re-sync it (a second place to
keep the immutability/versioning invariants ADR-011 already enforces once,
in Postgres), for a field the graph layer never actually queries by.

**Consequence:** a blast-radius or dependency-listing API response can
name and identify an affected component, but a caller who needs to know
*what changed about it* still goes to `GET
/projects/{id}/components/{id}/versions/latest` — which is the correct
system to ask, since that's where the immutable, checksummed truth lives.

## ADR-014 — Ten fixed relationship types, validated by a closed (source_type, relationship_type, target_type) allow-list (2026-09-13)

**Decision:** `DependencyRelationshipType` is a ten-member `StrEnum`
(`USES_MODEL`, `USES_PROMPT`, `CALLS`, `BELONGS_TO`, `USES_SCHEMA`,
`CALLS_API`, `CONTAINS`, `DEPENDS_ON`, `APPLIES_TO`, `PROVIDED_BY`), and
`app/domain/relationship_rules.py` holds a `frozenset` of exactly which
`(source ComponentType, relationship_type, target ComponentType)` triples
are semantically valid (e.g. `(AGENT, CALLS, TOOL)` is allowed;
`(MODEL, CALLS, WORKFLOW)` is not). `DependencyGraphService.
create_dependency` calls `validate_relationship()` before any Neo4j write
reaches the repository layer.

**Why centralized and closed, not open/extensible-by-string:** the spec
explicitly requires rejecting nonsensical relationships (its own example:
a Model can't CALL a Workflow), and requires this rule live in exactly one
tested place rather than being re-implemented per route or per service
method. A closed allow-list (rather than, say, "anything goes, reject only
an explicit denylist") also means adding an eleventh relationship type
later is a deliberate, reviewed addition to both the enum and the
allow-list — never an accidental new capability from a typo'd string
reaching Neo4j. `test_relationship_rules.py::
test_every_relationship_type_is_used_by_at_least_one_allowed_triple`
guards the enum and the allow-list from drifting apart in either
direction.

**Alternative considered:** validating shape with a lighter rule (e.g. "any
type may `DEPENDS_ON` any type, but the other nine are type-restricted") —
rejected as under-specified; the spec's own example needs a real per-triple
table, not a partial rule with exceptions.

## ADR-013 — Phase 3 network/Docker verification gap persists (2026-09-13)

**Context:** Same restriction as ADR-005/ADR-006, re-confirmed for Phase 3:
`pytest`/`mypy` against real deps and `alembic upgrade` could not be run.

**What was verified instead:** migrations 0001 and 0002 were hand-
transcribed into raw SQL and applied together against real Postgres 16
(`agentabi_test`), then every new behavior was exercised directly: unique
`(project_id, component_type, slug)`, same slug allowed under a different
`component_type`, `sequence` auto-incrementing per insert, unique
`(component_id, version)`, the immutability trigger rejecting a `content`
update while allowing a `metadata` update, and cascade delete removing a
component's versions. Ruff (format + lint) and `python -m py_compile`
passed clean on every new file.

**Action for the user:** same as ADR-005/ADR-006 — run `make install &&
make lint && make typecheck && make test && make migrate` in an
environment with normal PyPI/Docker access before treating Phase 3 as
fully proven.

## ADR-012 — Checksum: canonicalized-JSON SHA-256, computed from content only (2026-09-13)

**Decision:** `compute_checksum()` serializes the content dict with sorted
keys and compact separators (`json.dumps(..., sort_keys=True,
separators=(",", ":"))`), then SHA-256 hashes the UTF-8 bytes. Only the
validated `content` dict is hashed — never `id`, `created_at`, `sequence`,
or `metadata`.

**Why:** Determinism requires that key order (a Python dict iteration
detail, not semantic content) never changes the hash, and that volatile/
non-semantic fields never participate — two versions of *different*
components with identical `content` should (and, verified in testing, do)
hash identically, which is exactly the "did anything actually change"
signal later compatibility scans need.

**Alternative considered:** hashing the raw JSON string the client sent —
rejected because it would make the checksum depend on incidental
formatting (whitespace, key order) rather than semantic content, defeating
the purpose.

## ADR-011 — Version immutability enforced at both the service boundary and the database (2026-09-13)

**Decision:** `ComponentRegistryService` exposes no method to modify or
delete an existing `ComponentVersion`. Independently, a Postgres trigger
(`prevent_component_version_mutation`, created in migration `0002`) raises
an exception on any `UPDATE` that changes `content` or `checksum`.
`metadata` remains mutable (it's explicitly non-semantic — annotations,
not content).

**Why two layers:** The service-layer omission stops the 99% case (nobody
building on top of this API can accidentally or intentionally mutate a
version). The trigger stops the remaining case: a raw SQL migration, an
admin console, or a future service that talks to Postgres directly and
bypasses `ComponentRegistryService` entirely. The project's rule against
"faking" immutability through comments alone is exactly what this guards
against — verified by directly attempting the UPDATE in psql (see
Verification) and in `tests/test_component_registry_service.py`.

## ADR-010 — `sequence` (Postgres IDENTITY) for "latest version," not a `latest_version_id` pointer (2026-09-13)

**Decision:** `component_versions.sequence` is a `BIGINT GENERATED BY
DEFAULT AS IDENTITY` column, globally monotonic (not per-component), with
an index on `(component_id, sequence DESC)`. "Latest version of a
component" = `ORDER BY sequence DESC LIMIT 1`.

**Why not `created_at`:** Postgres `timestamptz` has microsecond
resolution, but two versions inserted in the same request/transaction (or
under high concurrency) could plausibly tie, making "latest" ambiguous.
`sequence` can't tie — it's assigned atomically by the database.

**Why not a `components.latest_version_id` FK:** That requires a circular
foreign-key relationship between `components` and `component_versions`
(each table needs the other to exist first), forcing the FK to be added
in a second migration step after both tables exist, plus a read-modify-
write on `components` for every new version (a write-amplifying,
race-condition-prone pattern for something a simple indexed query already
answers cheaply). The spec explicitly defers "active/production version"
pointer semantics to a later phase — this design doesn't block adding one
then, it just doesn't build it prematurely now.

## ADR-009 — Generic `components` + `component_versions`, not one table per component type (2026-09-13)

**Decision:** A single `components` table (identity: type, name, slug,
status, tenant scope) and a single `component_versions` table (immutable
content snapshot, JSONB `content` column), rather than
`prompts`/`models`/`tools`/... as separate tables.

**Why:** All ten component types share an identical lifecycle — register,
version, list, get-latest, deprecate — and every later phase that touches
components generically (Neo4j sync in Phase 4, compatibility scans in
Phase 5, blast-radius traversal) wants to query/iterate "all components in
a project" or "all versions of this component" without ten near-duplicate
code paths or a UNION across ten tables.

**Tradeoff being made:** Postgres can't enforce a `prompts.template
NOT NULL`-style column constraint on `content`, since `content` is JSONB
and its shape depends on `component_type`. That type safety is provided by
the application instead — `app/domain/component_content.py`'s per-type
Pydantic models with `extra="forbid"`, enforced in
`ComponentRegistryService.create_component_version` before anything is
persisted. This is a deliberate application/database responsibility split:
the database guarantees identity/versioning invariants (uniqueness, FKs,
immutability); the application guarantees content shape.

**Alternative considered:** a `components`/`component_versions` pair *plus*
ten type-specific tables joined 1:1 to `component_versions` (e.g.
`prompt_version_details`) for real column-level constraints — rejected for
this phase as premature normalization; nothing yet needs to `WHERE
prompt_version_details.template LIKE ...` at the SQL level, and it would
require a migration per component type instead of one.

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

*Image choice superseded by ADR-076 (2026-09-15): `bitnami/kafka` became
unresolvable on Docker Hub; replaced with `apache/kafka`. The KRaft/
no-Zookeeper decision below is unaffected.*

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

## ADR-043 — Fixed-window Redis rate limiting, fail-closed on Redis failure (2026-09-14)

Chose a fixed-window algorithm (key embeds `now // window_seconds`) over
sliding-window/token-bucket: it needs one Redis key per (bucket,
identity, window) with a plain `EXPIRE`, no sorted sets or background
cleanup, and is exact enough for abuse protection at this scale. A Lua
script (`EVAL`) combines `INCR` and a first-hit-only `EXPIRE` into one
atomic operation, closing the race where two concurrent requests'
separate `INCR`/`EXPIRE` calls could leave a key with no TTL. Verified
for real against a local Redis server via raw `redis-cli EVAL` (the
Python `redis` client is not installable in this sandbox): atomic
increment, first-hit TTL set, threshold enforcement, independent
principals, reset after expiry, and two independent `redis-cli`
invocations incrementing the same key to prove cross-process/distributed
correctness — all confirmed.

Failure policy is fail-closed and singular, not configurable per
endpoint: if Redis can't be reached, `RedisRateLimiter.check()` raises
`RateLimiterUnavailable`, mapped to HTTP 503 — never silently letting
rate-limited traffic through. An initial `rate_limit_fail_open` setting
was removed before this phase shipped in favor of this one documented
policy, per the spec's explicit allowance to centralize a single choice
rather than build per-endpoint toggles nothing yet needs.

## ADR-044 — Rate-limit identity: user id when authenticated, else trusted-proxy-aware client IP (2026-09-14)

`rate_limit_by_user` keys on `AuthenticatedPrincipal.user_id` (already
resolved by `get_current_user` for mutation/scan/replay routes — no
extra auth cost). `rate_limit_by_client` (GitHub OAuth login/callback,
which run before any AgentABI identity exists) keys on the direct ASGI
peer address unless `TRUSTED_PROXY_COUNT` > 0, in which case the Nth
`X-Forwarded-For` entry from the right is trusted instead. Default 0
means "trust nothing from request headers" — correct for local dev and
any deployment without a reverse proxy in front of the API; production
behind exactly one trusted proxy (e.g. an ALB) sets this to 1. Never the
full header as-is: every entry left of the trusted proxy's own appended
entries is caller-supplied and trivially spoofable.

## ADR-045 — Standardized error envelope; CSP intentionally not set at the API layer (2026-09-14)

Every error response (domain exceptions, FastAPI/Pydantic validation
errors, and unhandled exceptions) now returns
`{"error": {"code", "message", "request_id"}}`, replacing the old
`{"detail": ...}` shape. `request_id` is the correlation id
`CorrelationIdMiddleware` now also sets on `request.state` (not just
structlog's contextvars), read directly by the exception handlers in
`app/api/v1/errors.py`. Domain exceptions map through a single
class->`(status, code)` table instead of ~25 hand-written decorators;
`RequestValidationError` omits the raw `input` value from each field
error (never echoes back a submitted secret or oversized value); the
catch-all `Exception` handler logs full detail server-side via
`logger.exception()` and returns only a generic message + code +
request_id to the client.

`Content-Security-Policy` is deliberately not emitted anywhere in this
API: it's a JSON API whose own `/docs` (Swagger UI) loads assets from a
CDN, and a CSP strict enough to matter would break that. CSP ownership
belongs to the frontend/reverse-proxy layer, not this service.
`Strict-Transport-Security` is emitted only when `Settings.is_production`
is true — never in local HTTP dev.

## ADR-046 — Request-size limiting as raw ASGI middleware, not `BaseHTTPMiddleware` (2026-09-14)

`RequestSizeLimitMiddleware` wraps the ASGI `receive` callable directly
and counts each `http.request` chunk's byte length as it streams
through, aborting with a 413 once `MAX_REQUEST_BODY_BYTES` is exceeded.
`BaseHTTPMiddleware` was rejected because it must fully buffer the body
to inspect it — exactly the cost a size limit exists to avoid — and
that buffering would replace the request's body stream, breaking
Security Phase E's planned GitHub webhook HMAC verification, which needs
the exact raw bytes GitHub sent. This middleware never buffers or
rewrites the body beyond counting, so the raw stream stays verifiable
downstream in Phase E.

## ADR-047 — GitHub webhook trust boundary: verify raw bytes, then and only then trust anything (2026-09-14)

`POST /api/v1/github/webhook` is unauthenticated by AgentABI JWT — GitHub
proves itself via `X-Hub-Signature-256` instead. Verification
(`app/github/webhook_signature.py`) runs HMAC-SHA256 over the exact raw
request body bytes (`await request.body()`, never a re-serialized JSON
representation) using `hmac.compare_digest` for constant-time
comparison, and rejects a missing header, wrong prefix, malformed hex,
or wrong-length digest the same uniform way an invalid signature is
rejected (mirrors `InvalidToken`'s ADR-032 precedent — no oracle for
which check failed). Only after verification succeeds does anything
about the request — headers (`X-GitHub-Delivery`/`X-GitHub-Event`) or
payload — get trusted. Phase D's `RequestSizeLimitMiddleware` only
counts streamed bytes without altering them, so it does not interfere
with this raw-body requirement, and this route's own downstream JSON
parse (`json.loads`) is only a well-formedness check — no field of the
parsed payload is trusted or persisted yet (product processing is
Phase 12).

## ADR-048 — Delivery idempotency: unique `delivery_id`, SHA-256 payload-hash conflict detection (2026-09-14)

`github_webhook_deliveries.delivery_id` (GitHub's `X-GitHub-Delivery`)
has a database unique constraint — the idempotency backstop, not just an
application pre-check, so two concurrent redeliveries can never both
insert (same IntegrityError-retry pattern as
`TrajectoryRecorderService.start_trajectory`). A redelivery with an
identical SHA-256 payload hash is treated as an idempotent no-op success
(spec §9); a redelivery reusing the same id with a *different* hash is
a `WebhookDeliveryConflict` (409) — GitHub does not reuse delivery ids
for different payloads, so this is a genuine anomaly, not a retry. The
full payload is deliberately not stored, only its hash and event-type
metadata (spec §8) — this table is a delivery ledger, not a payload
archive.

## ADR-049 — Audit events: append-only via DB trigger, tenant-scoped by organization_id, OWNER/ADMIN-only read (2026-09-14)

`AuditEvent` (`app/models/audit_event.py`) has no update/delete method
on `AuditService`/`AuditEventRepository`, and migration 0007 adds a
database trigger blocking both UPDATE and DELETE unconditionally (same
posture as `TrajectoryEvent`/`ReplayStep`, extended here to also cover
DELETE — ADR-XXX precedent, `docs/DECISIONS.md` migration 0003/0004).
`organization_id`/`actor_user_id` use `ON DELETE SET NULL`, not the
`CASCADE` every tenant-scoped table elsewhere uses, so deleting an
organization or user can never silently delete the record of what it
did. `Permission.AUDIT_READ` (`app/authz/permissions.py`) is granted to
ADMIN and OWNER, denied to MEMBER — the same privileged-engineering-
action bucket as `SCAN_EXECUTE`/`REPLAY_EXECUTE`. `GET /api/v1/
organizations/{organization_id}/audit-events` is always tenant-scoped
by the path's `organization_id` via `require_organization_permission`
(no "list all organizations" variant exists). Metadata is redacted
through the same `sanitize()` every trajectory event payload uses,
extended in Phase D to also cover `client_secret`/`jwt_secret`/
`webhook_secret` — callers are still expected to pass allow-listed
fields, not arbitrary request dumps (spec §14).

Two centralized audit-emission points were wired this phase, deliberately
avoiding a broader cross-cutting rewrite: `GitHubOAuthService` records
`LOGIN_SUCCESS`/`LOGIN_FAILURE` (state-invalid and authorization-denied
cases only — never a provider token or OAuth state value), and
`AuthorizationService._record_denial` records `AUTHORIZATION_DENIED`
whenever `PermissionDenied` is raised (membership exists but lacks the
permission) — not for the 404 cross-tenant cases, which stay
indistinguishable-from-not-found by design (ADR-042). Both commit
immediately before raising, since `get_db_session`'s automatic rollback
on exception would otherwise discard the audit write along with it.
`PROJECT_CREATED`/`SCAN_TRIGGERED`/`REPLAY_TRIGGERED` audit actions
exist in the taxonomy but are not yet emitted anywhere — wiring them
requires threading actor/organization context into services that don't
currently take it, out of scope for this phase's token budget; left as
a scoped TODO for a future pass rather than a partial/inconsistent
cross-cutting change.
