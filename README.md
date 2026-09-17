# AgentABI

Agent Compatibility & Upgrade Intelligence Platform — determines whether a
change to an AI-agent system (model, prompt, MCP server/tool, schema, API,
policy, or workflow) is safe to deploy, using deterministic schema diffing,
dependency-graph blast-radius analysis, and trajectory replay. LLMs explain
evidence; they never make the PASS/WARN/BLOCK decision.

See `docs/PROJECT_SPEC.md` for the full spec, `docs/ARCHITECTURE.md` for the
current implementation, `docs/DECISIONS.md` for the ADR log, and
`docs/ROADMAP.md` for build status.

## Local development

```bash
cp .env.example .env
make install       # creates backend/.venv and installs deps
make infra-up       # postgres, redis, neo4j, kafka via docker compose
make migrate         # alembic upgrade head
make run             # uvicorn app.main:app --reload
```

```bash
make fmt         # ruff format + fix
make lint         # ruff check
make typecheck   # mypy
make test          # pytest
```

`make test` needs a `python3.12` on your PATH (that's what `make venv`
builds `backend/.venv` from). If your machine's default Python is a
different version (e.g. 3.13) and you don't have 3.12 installed
separately, run the suite in Docker instead — a real Python 3.12
container with the same `[dev]` dependencies CI installs, built from a
dedicated `test` stage that never ships in the `api`/`worker` production
image:

```bash
make infra-up            # postgres, neo4j (test depends on both)
docker compose run --rm test
```

`GET /api/v1/health` reports process liveness. `GET /api/v1/ready` reports
whether Postgres is actually reachable (503 if not).

## Frontend

```bash
cp frontend/.env.example frontend/.env.local
make frontend        # npm install && npm run dev, or cd frontend && npm run dev
```

Standalone Next.js app in `frontend/`, independently runnable from the
backend — see docs/ARCHITECTURE.md's Phase 14 section for structure,
auth flow, and the API-client/TanStack Query boundary. GitHub OAuth
requires setting the backend's `github_oauth_redirect_uri` to the
frontend's own `/auth/callback` route (see docs/DECISIONS.md ADR-070).

## Tracing

Distributed tracing (OpenTelemetry) is off by default
(`OTEL_ENABLED=false`) and never required for normal operation. To try
it locally: `docker compose up -d otel-collector`, set
`OTEL_ENABLED=true` for the API/worker, and watch collector stdout for
spans. See docs/ARCHITECTURE.md's Phase 15 section.

## Metrics

Prometheus metrics are on by default (`METRICS_ENABLED=true`), exposed
at `GET /metrics` (no AgentABI JWT — meant for a local/internal-network
scraper; see docs/ARCHITECTURE.md's Phase 16 section for the documented
security boundary). Separate from tracing: `prometheus_client` owns
metrics directly, never through OpenTelemetry (ADR-073). Run `docker
compose up -d prometheus grafana` to try it locally — Prometheus at
`http://localhost:9090` (targets: `api:8000`, `worker:9101`), Grafana at
`http://localhost:3001` (`admin` / `GRAFANA_ADMIN_PASSWORD`, default a
local-only placeholder) with the "AgentABI — System Overview" dashboard
auto-provisioned.

## Security & API

Access to non-public APIs requires an AgentABI JWT obtained via GitHub
OAuth2 (`/api/v1/auth/github/login`); authorization is RBAC
(OWNER/ADMIN/MEMBER) reloaded from the database per request and scoped to
organizations/projects (tenant isolation — cross-tenant access returns 404,
not 403). APIs are Pydantic-validated, Redis-rate-limited, and return a
standardized JSON error envelope. Inbound GitHub webhooks are verified via
HMAC-SHA256 (`X-Hub-Signature-256`) rather than a JWT, and admin actions are
recorded in an append-only audit log. Swagger UI is at `/docs` (Authorize
with a Bearer JWT); a Postman collection is in `postman/` — see
`docs/POSTMAN.md`. Full design in `docs/ARCHITECTURE.md`'s Security
Architecture Overview and `docs/SECURITY_VERIFICATION.md`.
