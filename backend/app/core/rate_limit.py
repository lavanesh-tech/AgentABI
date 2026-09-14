"""Redis-backed distributed rate limiting (Security Phase D spec §3/§4).

Algorithm: fixed window. The key embeds the current window index
(`now // window_seconds`), so a window boundary is just "a new Redis
key" — no separate cleanup job, and Redis's own key TTL reclaims the
old window automatically. Atomicity across concurrent requests (from
this process or any other API instance — the whole point of Redis over
a process-local dict) comes from a small Lua script executed with
`EVAL`: `INCR` and, only on the first increment, `EXPIRE`, as one
atomic operation. Two `INCR`+separate-`EXPIRE` calls from different
requests could otherwise interleave and leave a key with no TTL at all
(the first request's `EXPIRE` racing a second request's `INCR`); the
Lua script closes that race the same way `EVAL`-based counters
typically do.

`redis` (the Python client) is a declared dependency (pyproject.toml)
but not installable in this sandbox (same PyPI-403 restriction as
every prior phase), so `RedisRateLimiter` type-hints against
`redis.asyncio.Redis` under `TYPE_CHECKING` only and is exercised here
via `redis-cli EVAL` against a real local Redis server, not the Python
client — see docs/ARCHITECTURE.md. `InMemoryRateLimiter` is a
deterministic, clock-injectable fake for unit tests only (mirrors
`InMemoryOAuthStateStore`, Phase B) — never wired into production.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.domain.exceptions import RateLimited, RateLimiterUnavailable

if TYPE_CHECKING:
    from redis.asyncio import Redis

# INCR the counter; only the request that creates the key (count == 1)
# sets its expiry, so the window's TTL is set exactly once regardless of
# how many concurrent requests race to increment it.
_FIXED_WINDOW_SCRIPT = """
local current = redis.call("INCR", KEYS[1])
if current == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return current
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult: ...


def build_key(bucket: str, identity: str, *, window_seconds: int, now: float | None = None) -> str:
    """Deterministic key construction (spec §4): `rate:{bucket}:
    {identity}:{window_index}`. `identity` is never logged or returned
    to the client raw beyond what the caller already had (a user id or
    a client IP) — this function only shapes the Redis key."""

    current_time = now if now is not None else time.time()
    window_index = int(current_time // window_seconds)
    return f"rate:{bucket}:{identity}:{window_index}"


def retry_after_seconds(window_seconds: int, *, now: float | None = None) -> int:
    current_time = now if now is not None else time.time()
    elapsed_in_window = current_time % window_seconds
    return max(1, int(window_seconds - elapsed_in_window))


class RedisRateLimiter:
    """Production implementation. Untyped-at-runtime `redis_client`
    (only `TYPE_CHECKING`-imported above) so this class is constructible
    without the `redis` package installed — mirrors
    `RedisOAuthStateStore` (Phase B)."""

    def __init__(self, redis_client: "Redis") -> None:
        self._redis = redis_client

    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        try:
            current = await self._redis.eval(_FIXED_WINDOW_SCRIPT, 1, key, window_seconds)
        except Exception as exc:  # redis.RedisError, connection errors, ...
            raise RateLimiterUnavailable() from exc
        current = int(current)
        allowed = current <= limit
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - current),
            retry_after_seconds=retry_after_seconds(window_seconds),
        )


class InMemoryRateLimiter:
    """Deterministic, in-memory, test-only implementation. `now`
    defaults to `time.time` but accepts an injectable clock, same
    pattern as `InMemoryOAuthStateStore`."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._counts: dict[str, int] = {}

    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitResult:
        current = self._counts.get(key, 0) + 1
        self._counts[key] = current
        allowed = current <= limit
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - current),
            retry_after_seconds=retry_after_seconds(window_seconds, now=self._now()),
        )


async def enforce(
    limiter: RateLimiter,
    *,
    bucket: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    """Shared enforcement path for every rate-limit dependency
    (`app/api/deps/rate_limit.py`): builds the key, checks it, and
    raises the standardized `RateLimited`/`RateLimiterUnavailable`
    domain errors — never a bare Redis exception, never a silently
    skipped check (spec §9's fail-closed policy: a
    `RateLimiterUnavailable` here becomes an HTTP 503 centrally, it
    never falls through to "allowed")."""

    key = build_key(bucket, identity, window_seconds=window_seconds)
    result = await limiter.check(key, limit=limit, window_seconds=window_seconds)
    if not result.allowed:
        raise RateLimited(retry_after_seconds=result.retry_after_seconds)
