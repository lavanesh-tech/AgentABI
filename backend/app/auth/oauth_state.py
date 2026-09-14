"""OAuth `state` store — CSRF protection for the GitHub OAuth2 login flow
(Security Phase B spec §5). A `state` value must be cryptographically
random, expire, and be consumable exactly once; this module is the one
place that contract is implemented and tested.

Only the state's SHA-256 hash is ever stored (spec §5: "do not store the
raw state unnecessarily if a hash is sufficient") — the raw value only
ever exists in the redirect URL and the caller's browser.

`RedisOAuthStateStore` is the only production implementation, using
Redis's atomic `GETDEL` (available since Redis 6.2) so "check exists,
still fresh, and consumed" happens as a single operation — no
check-then-delete race between two concurrent callback requests replaying
the same state. `redis` is a declared dependency (pyproject.toml) but
not importable in this sandbox (same PyPI-403 restriction as every prior
phase); this module type-hints against `redis.asyncio.Redis` under
`TYPE_CHECKING` only, so it stays import-safe without the package
installed, and is exercised only via `InMemoryOAuthStateStore` here.

`InMemoryOAuthStateStore` is a deterministic, clock-injectable fake for
unit tests only — never wired into production (mirrors
`FakeReplayExecutor`, Phase 7 §9). It is NOT a production fallback: if
Redis is unavailable, `RedisOAuthStateStore` raises
`OAuthStateStoreUnavailable` rather than the caller silently swapping in
an in-process dict (spec §5 explicitly forbids that).
"""

import hashlib
import secrets
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from app.domain.exceptions import OAuthStateStoreUnavailable

if TYPE_CHECKING:
    from redis.asyncio import Redis

_KEY_PREFIX = "oauth_state:"


def generate_state() -> str:
    """A cryptographically random, URL-safe state value (256 bits of
    entropy — `secrets.token_urlsafe` uses `os.urandom`, spec §5)."""
    return secrets.token_urlsafe(32)


def _hash_state(state: str) -> str:
    return _KEY_PREFIX + hashlib.sha256(state.encode("utf-8")).hexdigest()


class OAuthStateStore(Protocol):
    """Save a freshly generated state with a TTL, and consume (validate +
    atomically invalidate) it exactly once on callback."""

    async def save(self, state: str, *, ttl_seconds: int) -> None: ...

    async def consume(self, state: str) -> bool: ...


class RedisOAuthStateStore:
    """Production implementation. `redis_client` is any object exposing
    async `set`/`getdel` with `redis.asyncio.Redis`'s signatures — kept
    untyped-at-runtime (only under `TYPE_CHECKING` above) so this class
    is constructible/importable without the `redis` package present."""

    def __init__(self, redis_client: "Redis") -> None:
        self._redis = redis_client

    async def save(self, state: str, *, ttl_seconds: int) -> None:
        from app.observability import start_span

        # spec §18: never the state value itself on the span — only
        # that a save happened.
        with start_span("redis.oauth_state.save", kind="client"):
            try:
                # NX: a collision would mean two identical 256-bit random
                # values were generated independently — treat that as a
                # hard failure rather than silently overwriting.
                await self._redis.set(_hash_state(state), "1", ex=ttl_seconds, nx=True)
            except Exception as exc:  # redis.RedisError, connection errors, ...
                raise OAuthStateStoreUnavailable() from exc

    async def consume(self, state: str) -> bool:
        from app.observability import start_span

        with start_span("redis.oauth_state.consume", kind="client"):
            try:
                value = await self._redis.getdel(_hash_state(state))
            except Exception as exc:
                raise OAuthStateStoreUnavailable() from exc
            return value is not None


class InMemoryOAuthStateStore:
    """Deterministic, in-memory, test-only store. `now` defaults to
    `time.time` but accepts an injectable clock so expiry/reuse can be
    tested without real sleeps."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._entries: dict[str, float] = {}  # hashed state -> expires_at

    async def save(self, state: str, *, ttl_seconds: int) -> None:
        self._entries[_hash_state(state)] = self._now() + ttl_seconds

    async def consume(self, state: str) -> bool:
        key = _hash_state(state)
        expires_at = self._entries.pop(key, None)
        if expires_at is None:
            return False
        return self._now() < expires_at
