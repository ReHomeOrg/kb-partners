"""Юнит-тест HttpConciergeClient через httpx.MockTransport (Bearer/идемпотентность/исход)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.concierge import HttpConciergeClient
from api.clients.errors import ExternalServiceError
from api.clients.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]

_PAYLOAD = {
    "session_id": "s1",
    "text": "Заявка RQ-1 отменена.",
    "ref": "RQ-1",
    "status": "CANCELLED",
    "request_id": "r1",
}


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _client(handler: Handler, sleep: SleepFn, *, attempts: int = 1) -> HttpConciergeClient:
    http = httpx.AsyncClient(base_url="http://concierge", transport=httpx.MockTransport(handler))
    resilient = ResilientHttpClient(
        client_name="concierge",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=attempts),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return HttpConciergeClient(http_client=resilient, token_provider=StaticTokenProvider("tok"))


async def test_deliver_posts_bearer_idempotency_and_body(noop_sleep: SleepFn) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/concierge/inbound/status-update"
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["idempotency-key"] == "concierge-status:r1:CANCELLED"
        # Тело — только контрактные поля; request_id наружу НЕ уходит (только в ключ).
        assert json.loads(request.content) == {
            "session_id": "s1",
            "text": "Заявка RQ-1 отменена.",
            "ref": "RQ-1",
            "status": "CANCELLED",
        }
        return httpx.Response(202)

    assert await _client(handler, noop_sleep).deliver_status_update(_PAYLOAD) is True


async def test_deliver_non_2xx_returns_false(noop_sleep: SleepFn) -> None:
    result = await _client(lambda _r: httpx.Response(409), noop_sleep).deliver_status_update(
        _PAYLOAD
    )
    assert result is False


async def test_deliver_unavailable_raises(noop_sleep: SleepFn) -> None:
    # 5xx после ретраев → ExternalServiceError (durable-ретрай на дрейне, kb-partners не падает).
    with pytest.raises(ExternalServiceError):
        await _client(lambda _r: httpx.Response(503), noop_sleep).deliver_status_update(_PAYLOAD)
