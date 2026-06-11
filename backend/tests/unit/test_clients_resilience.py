"""Юнит-тесты resilience-примитивов клиентов: retry, circuit breaker, cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest

from api.clients.cache import InMemoryCache
from api.clients.circuit_breaker import CircuitBreaker, CircuitState
from api.clients.retry import RetryPolicy, retry_async

SleepFn = Callable[[float], Awaitable[None]]


class MutableClock:
    """Управляемые часы для тестов breaker/cache (инжектируется как `now`)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock()


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


# --- retry ----------------------------------------------------------------


async def test_retry_succeeds_without_retry(noop_sleep: SleepFn) -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    out = await retry_async(fn, RetryPolicy(attempts=3), retry_on=(ValueError,), sleep=noop_sleep)
    assert out == "ok"
    assert calls == 1


async def test_retry_recovers_after_failures() -> None:
    calls = 0
    delays: list[float] = []

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("transient")
        return "ok"

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    out = await retry_async(
        fn,
        RetryPolicy(attempts=3, base_delay=0.1, max_delay=2.0),
        retry_on=(ValueError,),
        sleep=sleep,
    )
    assert out == "ok"
    assert calls == 3
    assert delays == [0.1, 0.2]


async def test_retry_exhausts_and_raises_last(noop_sleep: SleepFn) -> None:
    async def fn() -> str:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await retry_async(fn, RetryPolicy(attempts=2), retry_on=(ValueError,), sleep=noop_sleep)


async def test_retry_non_retryable_propagates(noop_sleep: SleepFn) -> None:
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise KeyError("k")

    with pytest.raises(KeyError):
        await retry_async(fn, RetryPolicy(attempts=3), retry_on=(ValueError,), sleep=noop_sleep)
    assert calls == 1


def test_retry_policy_rejects_zero_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        RetryPolicy(attempts=0)


def test_backoff_caps_at_max() -> None:
    policy = RetryPolicy(attempts=10, base_delay=1.0, max_delay=3.0)
    assert [policy.backoff(n) for n in (1, 2, 3, 5)] == [1.0, 2.0, 3.0, 3.0]


# --- circuit breaker ------------------------------------------------------


async def test_breaker_opens_after_threshold(clock: MutableClock) -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_timeout=10, now=clock)
    assert await cb.acquire() is True
    await cb.record_failure()
    # Свежий локал перед каждым assert: иначе mypy сужает cb.state до Literal и
    # ругается non-overlapping на следующем сравнении.
    state = cb.state
    assert state is CircuitState.CLOSED
    await cb.record_failure()
    state = cb.state
    assert state is CircuitState.OPEN
    assert await cb.acquire() is False


async def test_breaker_half_open_probe_then_close(clock: MutableClock) -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=10, now=clock)
    await cb.acquire()
    await cb.record_failure()
    state = cb.state
    assert state is CircuitState.OPEN
    assert await cb.acquire() is False
    clock.now = 10
    assert await cb.acquire() is True  # одна проба
    state = cb.state
    assert state is CircuitState.HALF_OPEN
    assert await cb.acquire() is False  # параллельные отклонены
    await cb.record_success()
    state = cb.state
    assert state is CircuitState.CLOSED


async def test_breaker_half_open_failure_reopens(clock: MutableClock) -> None:
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=5, now=clock)
    await cb.acquire()
    await cb.record_failure()
    clock.now = 5
    assert await cb.acquire() is True
    await cb.record_failure()
    assert cb.state is CircuitState.OPEN


def test_breaker_rejects_zero_threshold() -> None:
    with pytest.raises(ValueError, match="failure_threshold"):
        CircuitBreaker(failure_threshold=0, reset_timeout=1, now=lambda: 0.0)


# --- cache ----------------------------------------------------------------


async def test_inmemory_cache_set_get_expire(clock: MutableClock) -> None:
    cache = InMemoryCache(now=clock)
    assert await cache.get("k") is None
    await cache.set("k", "v", ttl_seconds=10)
    assert await cache.get("k") == "v"
    clock.now = 10
    assert await cache.get("k") is None  # истёк TTL
