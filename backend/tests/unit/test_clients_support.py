"""Юнит-тесты клиента kb-support (claims) через httpx.MockTransport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy
from api.clients.support.adapter import HttpKbSupportClient

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _client(handler: Handler, sleep: SleepFn) -> HttpKbSupportClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://support")
    resilient = ResilientHttpClient(
        client_name="kb_support",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return HttpKbSupportClient(http_client=resilient, token_provider=StaticTokenProvider("tok"))


async def test_create_claim_maps_and_authorizes(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.headers["idempotency-key"] == "dispute:r1"
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(201, json={"id": "cl-1", "status": "OPEN"})

    client = _client(handler, noop_sleep)
    ref = await client.create_compensation_claim(
        request_id="r1", requester_id="u1", reason="bad", idempotency_key="dispute:r1"
    )
    assert ref is not None
    assert ref.id == "cl-1"
    assert ref.status == "OPEN"


async def test_create_claim_degrades_on_5xx(noop_sleep: SleepFn) -> None:
    client = _client(lambda req: httpx.Response(503), noop_sleep)
    ref = await client.create_compensation_claim(
        request_id="r1", requester_id="u1", reason="x", idempotency_key="k"
    )
    assert ref is None


async def test_create_claim_malformed_json_degrades(noop_sleep: SleepFn) -> None:
    client = _client(lambda req: httpx.Response(201, content=b"nope"), noop_sleep)
    ref = await client.create_compensation_claim(
        request_id="r1", requester_id="u1", reason="x", idempotency_key="k"
    )
    assert ref is None
