"""Юнит-тесты клиента rehome.one (settlement) через httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.rehome.adapter import HttpRehomeOneClient
from api.clients.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _client(handler: Handler, sleep: SleepFn) -> HttpRehomeOneClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://rehome")
    resilient = ResilientHttpClient(
        client_name="rehome_one",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return HttpRehomeOneClient(http_client=resilient, token_provider=StaticTokenProvider("tok"))


async def test_trigger_settlement_maps(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["idempotency-key"] == "settle:r1"
        return httpx.Response(
            201, json={"status": "PENDING", "amount_ref": "a-1", "escrow_ref": "e-1"}
        )

    client = _client(handler, noop_sleep)
    ref = await client.trigger_settlement(
        request_id="r1", service_order_id="so-1", idempotency_key="settle:r1"
    )
    assert ref is not None
    assert ref.amount_ref == "a-1"
    assert ref.escrow_ref == "e-1"


async def test_trigger_settlement_degrades_on_5xx(noop_sleep: SleepFn) -> None:
    client = _client(lambda req: httpx.Response(503), noop_sleep)
    ref = await client.trigger_settlement(
        request_id="r1", service_order_id=None, idempotency_key="k"
    )
    assert ref is None
