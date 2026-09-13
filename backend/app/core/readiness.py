"""Pluggable readiness-check registry.

`/ready` needs to report on more than one dependency (Postgres today,
Neo4j as of Phase 4, Redis/Kafka in later phases) without every new
dependency requiring a rewrite of the endpoint itself. Each check is a
zero-argument async callable returning `bool` — never raising — registered
here under a short name; `app/api/v1/health.py` just runs all of them and
aggregates the result. Liveness (`/health`) is deliberately untouched by
any of this: it must keep proving only "the process is up" and never
depends on an external service.
"""

from collections.abc import Awaitable, Callable

from app.core.database import check_database_connection
from app.graph.client import check_graph_connection

ReadinessCheck = Callable[[], Awaitable[bool]]

# Insertion order is preserved in the response for readability, but nothing
# depends on it: `/ready` is unavailable (503) if ANY check fails.
READINESS_CHECKS: dict[str, ReadinessCheck] = {
    "database": check_database_connection,
    "graph": check_graph_connection,
}


async def run_readiness_checks() -> dict[str, bool]:
    results: dict[str, bool] = {}
    for name, check in READINESS_CHECKS.items():
        results[name] = await check()
    return results
