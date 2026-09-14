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
