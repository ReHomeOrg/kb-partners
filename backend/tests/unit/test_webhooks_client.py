"""Юнит-тест доставки WebhookClient через httpx.MockTransport (подпись/исход)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy
from api.webhooks.client import WebhookClient, sign

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _webhook(handler: Handler, sleep: SleepFn) -> WebhookClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    resilient = ResilientHttpClient(
        client_name="webhook",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return WebhookClient(resilient, url="http://sub/hook", secret="sec")


async def test_deliver_signs_and_succeeds(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url == "http://sub/hook"
        assert req.headers["x-event"] == "request.created"
        assert req.headers["x-signature"] == sign("sec", req.content)
        return httpx.Response(200)

    assert await _webhook(handler, noop_sleep).deliver({"event": "request.created"}) is True


async def test_deliver_non_2xx_returns_false(noop_sleep: SleepFn) -> None:
    assert (
        await _webhook(lambda req: httpx.Response(404), noop_sleep).deliver({"event": "x"}) is False
    )
