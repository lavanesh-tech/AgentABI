FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps needed by psycopg (binary wheel used, so keep this minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
# alembic.ini's script_location=alembic (relative) and prepend_sys_path=.
# both assume the migration chain sits alongside app/ at this same
# WORKDIR (/app) — omitting these two made `alembic upgrade head` fail
# with "No config file 'alembic.ini' found" from inside the container,
# even though the app/ package (and alembic itself, via pyproject.toml)
# was already present. Not a startup dependency — nothing here runs
# migrations automatically — just what `docker compose exec api alembic
# upgrade head` needs to find on disk.
COPY alembic.ini ./
COPY alembic ./alembic

# ---------------------------------------------------------------------
# `runtime` — the production image. Only the runtime dependency set
# (pyproject.toml's [project.dependencies]) is installed here, never
# [dev] — this is the image `docker compose`'s `api`/`worker` services
# build and what ships to ECR (see deploy.yml); it must never grow test
# tooling. docker-compose.yml pins both of those services to
# `target: runtime` explicitly, and `deploy.yml`'s image build does too,
# so this stays the production image regardless of stage order below.
# ---------------------------------------------------------------------
FROM base AS runtime

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------
# `test` — local test/dev image only. Never built by deploy.yml, never
# pushed to a registry, and not part of `docker compose up`'s default
# service set (see docker-compose.yml's `test` service, which uses
# `profiles: ["test"]` and `target: test`) — this stage exists solely so
# `docker compose run --rm test` gives a real, reproducible Python 3.12
# environment with [dev] installed (pytest, pytest-asyncio, pytest-cov,
# ruff, mypy) for anyone whose host machine doesn't have Python 3.12
# available for the venv-based `make install`/`make test` path. Building
# FROM base (not FROM runtime) means it never inherits — and can never
# accidentally ship — the runtime stage's leaner, test-tooling-free
# install.
# ---------------------------------------------------------------------
FROM base AS test

COPY tests ./tests
COPY scripts ./scripts

RUN pip install --no-cache-dir ".[dev]"

CMD ["pytest", "--cov=app", "--cov-report=term-missing"]
