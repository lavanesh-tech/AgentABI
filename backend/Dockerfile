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

RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
