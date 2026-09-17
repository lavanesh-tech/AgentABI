"""Ensures the `agentabi_test` database exists before pytest runs against
it (docker compose `test` service only — see docker-compose.yml).

CI (.github/workflows/ci.yml) doesn't need this: its Postgres service
container is provisioned fresh per run with POSTGRES_DB=agentabi_test
directly. Locally, `docker compose`'s `postgres` service is long-lived
(a named volume) and only ever creates its POSTGRES_DB (`agentabi`) on
first init — the test database has to be created out-of-band, and this
has to be safe to run against an already-initialized volume, on every
`docker compose run --rm test`, not just the first one.

Uses `psycopg` (already a runtime dependency, not a dev-only one) rather
than requiring a `psql`/postgres-client apt package in the image.
"""

import os

import psycopg
from psycopg import errors

# Connects to the server's default database (never the test database
# itself — you can't CREATE DATABASE while connected to it) to issue the
# CREATE DATABASE. Defaults match docker-compose.yml's `postgres` service.
ADMIN_DSN = os.environ.get(
    "POSTGRES_ADMIN_DSN", "postgresql://agentabi:agentabi@postgres:5432/agentabi"
)
TEST_DB_NAME = os.environ.get("TEST_POSTGRES_DB", "agentabi_test")


def main() -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        try:
            # Identifier, not a value — can't be parameterized; TEST_DB_NAME
            # is operator-controlled local config, never user input.
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
            print(f"created database {TEST_DB_NAME!r}")
        except errors.DuplicateDatabase:
            print(f"database {TEST_DB_NAME!r} already exists — nothing to do")


if __name__ == "__main__":
    main()
