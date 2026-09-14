"""OAuth state store — pure unit tests (Security Phase B spec §16).
`InMemoryOAuthStateStore` has no SQLAlchemy/FastAPI/redis import, so
this runs for real via `pytest --noconftest`.

`pytest-asyncio` is not installed in this sandbox (same restriction as
every other dependency), so test functions stay synchronous and drive
the store's async methods with `asyncio.run` directly, rather than
relying on the plugin's auto-async-test support."""

import asyncio

from app.auth.oauth_state import InMemoryOAuthStateStore, generate_state


def test_generate_state_is_random_and_url_safe():
    a, b = generate_state(), generate_state()
    assert a != b
    assert len(a) >= 32
    assert all(c.isalnum() or c in "-_" for c in a)


def test_save_then_consume_succeeds_once():
    async def scenario() -> bool:
        store = InMemoryOAuthStateStore()
        state = generate_state()
        await store.save(state, ttl_seconds=60)
        return await store.consume(state)

    assert asyncio.run(scenario()) is True


def test_consume_is_one_time_use():
    async def scenario() -> tuple[bool, bool]:
        store = InMemoryOAuthStateStore()
        state = generate_state()
        await store.save(state, ttl_seconds=60)
        first = await store.consume(state)
        second = await store.consume(state)
        return first, second

    first, second = asyncio.run(scenario())
    assert first is True
    assert second is False  # reused


def test_consume_missing_state_fails():
    async def scenario() -> bool:
        store = InMemoryOAuthStateStore()
        return await store.consume("never-generated")

    assert asyncio.run(scenario()) is False


def test_consume_malformed_state_fails():
    async def scenario() -> tuple[bool, bool]:
        store = InMemoryOAuthStateStore()
        return await store.consume(""), await store.consume("not-a-real-state-value")

    empty_result, garbage_result = asyncio.run(scenario())
    assert empty_result is False
    assert garbage_result is False


def test_consume_expired_state_fails():
    clock = {"now": 1000.0}

    async def scenario() -> bool:
        store = InMemoryOAuthStateStore(now=lambda: clock["now"])
        state = generate_state()
        await store.save(state, ttl_seconds=10)
        clock["now"] = 1011.0  # past the 10s TTL
        return await store.consume(state)

    assert asyncio.run(scenario()) is False


def test_consume_state_that_does_not_match_a_generated_one_fails():
    async def scenario() -> bool:
        store = InMemoryOAuthStateStore()
        await store.save(generate_state(), ttl_seconds=60)
        return await store.consume(generate_state())

    assert asyncio.run(scenario()) is False


def test_different_states_are_independent():
    async def scenario() -> tuple[bool, bool]:
        store = InMemoryOAuthStateStore()
        state_a, state_b = generate_state(), generate_state()
        await store.save(state_a, ttl_seconds=60)
        await store.save(state_b, ttl_seconds=60)
        return await store.consume(state_a), await store.consume(state_b)

    result_a, result_b = asyncio.run(scenario())
    assert result_a is True
    assert result_b is True
