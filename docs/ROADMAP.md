# Roadmap

Status tracker for the 20-phase build order. Update the table at the end of
every phase.

| # | Phase | Status |
|---|-------|--------|
| 1 | Repository foundation + local Docker environment | ✅ Done (see caveat in DECISIONS.md ADR-005) |
| 2 | PostgreSQL + SQLAlchemy + Alembic | ⬜ Not started |
| 3 | Component Registry | ⬜ Not started |
| 4 | Neo4j dependency graph | ⬜ Not started |
| 5 | Compatibility / schema-diff engine | ⬜ Not started |
| 6 | Trajectory recording | ⬜ Not started |
| 7 | Replay engine | ⬜ Not started |
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
