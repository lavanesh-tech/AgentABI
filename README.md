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
