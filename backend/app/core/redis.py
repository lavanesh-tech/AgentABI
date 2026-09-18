"""Async Redis client lifecycle — mirrors `app/core/database.py`'s
process-wide-singleton pattern (created lazily, disposed explicitly on
shutdown). Introduced in Security Phase B for `RedisOAuthStateStore`;
nothing before this phase needed a live Redis connection.

`redis` is a declared dependency (pyproject.toml) but not installable in
this sandbox (same PyPI-403 restriction as every prior phase's deps), so
this module type-hints against `redis.asyncio.Redis` under
`TYPE_CHECKING` only and is not exercised by `pytest` here.
"""

from typing import TYPE_CHECKING

from app.core.config import Settings, get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

_redis_client: "Redis | None" = None


def get_redis_client(settings: Settings | None = None) -> "Redis":
    global _redis_client
    if _redis_client is None:
        from redis.asyncio import from_url

        settings = settings or get_settings()
        _redis_client = from_url(  # type: ignore[no-untyped-call]
            str(settings.redis_dsn), decode_responses=True
        )
    return _redis_client


async def dispose_redis_client() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
