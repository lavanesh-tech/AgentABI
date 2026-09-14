"""Rate limiter — pure unit tests (Security Phase D spec §22). Uses only
`InMemoryRateLimiter`/`build_key`/`retry_after_seconds`/`enforce` from
`app/core/rate_limit.py`, which has no SQLAlchemy/FastAPI/redis import,
so this runs for real via `pytest --noconftest`. Same `asyncio.run`
pattern as `tests/test_oauth_state.py` (no pytest-asyncio in this
sandbox).
"""

import asyncio

import pytest

from app.core.rate_limit import (
    InMemoryRateLimiter,
    build_key,
    enforce,
    retry_after_seconds,
)
from app.domain.exceptions import RateLimited


def test_build_key_is_deterministic_for_same_window():
    a = build_key("auth", "user-1", window_seconds=60, now=100.0)
    b = build_key("auth", "user-1", window_seconds=60, now=101.0)
    assert a == b


def test_build_key_changes_across_window_boundary():
    a = build_key("auth", "user-1", window_seconds=60, now=59.0)
    b = build_key("auth", "user-1", window_seconds=60, now=61.0)
    assert a != b


def test_build_key_distinguishes_bucket_and_identity():
    base = build_key("auth", "user-1", window_seconds=60, now=0.0)
    other_bucket = build_key("scan", "user-1", window_seconds=60, now=0.0)
    other_identity = build_key("auth", "user-2", window_seconds=60, now=0.0)
    assert base != other_bucket
    assert base != other_identity


def test_retry_after_seconds_counts_down_to_window_boundary():
    assert retry_after_seconds(60, now=30.0) == 30
    assert retry_after_seconds(60, now=59.5) == 1
    assert retry_after_seconds(60, now=0.0) == 60


def test_under_limit_is_allowed():
    async def scenario() -> bool:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        result = await limiter.check("k", limit=5, window_seconds=60)
        return result.allowed

    assert asyncio.run(scenario()) is True


def test_at_limit_is_allowed_over_limit_is_not():
    async def scenario() -> list[bool]:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        results = []
        for _ in range(6):
            result = await limiter.check("k", limit=5, window_seconds=60)
            results.append(result.allowed)
        return results

    results = asyncio.run(scenario())
    assert results == [True, True, True, True, True, False]


def test_distinct_identities_have_independent_counts():
    async def scenario() -> tuple[bool, bool]:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        for _ in range(5):
            await limiter.check("rate:auth:user-1:0", limit=5, window_seconds=60)
        user1_sixth = await limiter.check("rate:auth:user-1:0", limit=5, window_seconds=60)
        user2_first = await limiter.check("rate:auth:user-2:0", limit=5, window_seconds=60)
        return user1_sixth.allowed, user2_first.allowed

    sixth, other = asyncio.run(scenario())
    assert sixth is False
    assert other is True


def test_distinct_buckets_have_independent_counts_for_same_identity():
    async def scenario() -> bool:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        for _ in range(5):
            await limiter.check("rate:auth:user-1:0", limit=5, window_seconds=60)
        replay_first = await limiter.check("rate:replay:user-1:0", limit=5, window_seconds=60)
        return replay_first.allowed

    assert asyncio.run(scenario()) is True


def test_window_reset_allows_requests_again():
    async def scenario() -> tuple[bool, bool]:
        clock = {"t": 0.0}
        limiter = InMemoryRateLimiter(now=lambda: clock["t"])
        key_before = build_key("auth", "user-1", window_seconds=60, now=clock["t"])
        for _ in range(5):
            await limiter.check(key_before, limit=5, window_seconds=60)
        sixth = await limiter.check(key_before, limit=5, window_seconds=60)

        clock["t"] = 61.0
        key_after = build_key("auth", "user-1", window_seconds=60, now=clock["t"])
        first_in_new_window = await limiter.check(key_after, limit=5, window_seconds=60)
        return sixth.allowed, first_in_new_window.allowed

    sixth, new_window = asyncio.run(scenario())
    assert sixth is False
    assert new_window is True


def test_result_reports_retry_after_seconds():
    async def scenario() -> int:
        limiter = InMemoryRateLimiter(now=lambda: 10.0)
        result = await limiter.check("k", limit=1, window_seconds=60)
        return result.retry_after_seconds

    assert asyncio.run(scenario()) == 50


def test_enforce_raises_rate_limited_when_over_limit():
    async def scenario() -> None:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        for _ in range(3):
            await enforce(limiter, bucket="auth", identity="user-1", limit=3, window_seconds=60)
        await enforce(limiter, bucket="auth", identity="user-1", limit=3, window_seconds=60)

    with pytest.raises(RateLimited) as excinfo:
        asyncio.run(scenario())
    assert excinfo.value.retry_after_seconds > 0


def test_enforce_allows_requests_within_limit():
    async def scenario() -> None:
        limiter = InMemoryRateLimiter(now=lambda: 0.0)
        for _ in range(3):
            await enforce(limiter, bucket="auth", identity="user-1", limit=3, window_seconds=60)

    asyncio.run(scenario())  # should not raise
