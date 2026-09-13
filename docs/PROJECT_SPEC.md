# AgentABI — Project Specification

Agent Compatibility & Upgrade Intelligence Platform.

This file is the canonical, condensed spec. It exists so future sessions
don't need the full original prompt repeated. Read this before ARCHITECTURE.md
and ROADMAP.md.

## Core question

> If I change a model, prompt, MCP server, MCP tool, tool schema, structured
> output schema, API, policy, workflow, or agent configuration, what
> downstream behavior could break?

## Pipeline (target end-state)

```
GitHub PR
  → webhook validation
  → changed-component detection
  → baseline config loading
  → candidate config loading
  → schema/config diff
  → dependency graph traversal (blast radius)
  → historical trajectory selection
  → baseline replay
  → candidate replay
  → differential analysis
  → deterministic risk calculation
  → optional LLM explanation (never the decision)
  → GitHub Check / PR comment
  → PASS / WARN / BLOCK
```

## Hard rule: determinism

The PASS/WARN/BLOCK decision, schema-compatibility analysis, graph traversal,
and all metrics (latency/cost/success-rate/drift) are computed by **code**,
never by an LLM. LLMs may only summarize/explain evidence that already exists.

## Stack

- **Backend**: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, httpx
- **Data**: PostgreSQL (system of record), Redis (cache/locks/job state — never
  source of truth), Neo4j (dependency graph), Kafka (event backbone)
- **AI**: OpenAI + Gemini behind a `ModelProvider` abstraction; MCP support
- **Frontend**: Next.js, React, TypeScript, Tailwind, shadcn/ui, TanStack Query,
  React Flow, Recharts/ECharts
- **Observability**: OpenTelemetry, Prometheus, Grafana, structured JSON logs,
  correlation IDs
- **DevOps**: Docker/Compose, Kubernetes (+Helm where useful), Terraform,
  GitHub Actions
- **AWS**: EKS, RDS Postgres, MSK, ElastiCache Redis, S3, ECR, ALB, Route53,
  Secrets Manager, CloudWatch, IAM

## Backend module layout

```
backend/app/
  api/            # HTTP routers (versioned: api/v1/...)
  core/           # config, logging, middleware, cross-cutting concerns
  domain/         # framework-free domain models / value objects
  models/         # SQLAlchemy ORM models (Phase 2+)
  repositories/   # persistence access, one per aggregate
  services/       # business/orchestration logic
  compatibility/  # deterministic schema/config diff engine (Phase 5)
  replay/         # replay engine (Phase 7)
  graph/          # Neo4j dependency graph client + traversal (Phase 4)
  providers/      # OpenAI/Gemini provider abstraction (Phase 8/9)
  github/         # webhook handling, Checks API, PR comments (Phase 12)
  workers/         # Kafka consumers / background workers (Phase 13)
  telemetry/      # OpenTelemetry setup (Phase 15)
```

## Non-negotiables (from the working agreement)

1. One phase at a time; stop and wait after each phase completion summary.
2. Inspect before changing; never blindly rewrite files.
3. No fake functionality — no fabricated test results, benchmarks, or
   "should work" claims. Prove what can be proven; state plainly what
   couldn't be verified and why.
4. Every DB schema change goes through an Alembic migration.
5. Secrets only via environment variables; `.env` is gitignored;
   `.env.example` stays current.
6. Every phase ends with the fixed completion-summary format (see
   `docs/ROADMAP.md` for phase status and the working agreement for the
   exact format).

## Build order

See `docs/ROADMAP.md` for the 20-phase build order and current status.
