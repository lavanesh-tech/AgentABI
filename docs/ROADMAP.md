# Roadmap

Status tracker for the 20-phase build order. Update the table at the end of
every phase.

| # | Phase | Status |
|---|-------|--------|
| 1 | Repository foundation + local Docker environment | ✅ Done (see caveat in DECISIONS.md ADR-005) |
| 2 | PostgreSQL + SQLAlchemy + Alembic | ✅ Done (see caveat in DECISIONS.md ADR-006/ADR-008) |
| 3 | Component Registry | ✅ Done (see caveat in DECISIONS.md ADR-013) |
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
