"""Юнит-тесты ResilientHttpClient и platform-адаптера (httpx.MockTransport, без сети)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.cache import InMemoryCache
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.errors import CircuitOpenError, ExternalServiceError
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _resilient(
    handler: Handler, sleep: SleepFn, *, attempts: int = 3, threshold: int = 5
) -> ResilientHttpClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://neighbour")
    breaker = CircuitBreaker(failure_threshold=threshold, reset_timeout=30, now=lambda: 0.0)
    return ResilientHttpClient(
        client_name="test",
        http=http,
        breaker=breaker,
        retry=RetryPolicy(attempts=attempts),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )


# --- ResilientHttpClient --------------------------------------------------


async def test_request_success(noop_sleep: SleepFn) -> None:
    client = _resilient(lambda req: httpx.Response(200, json={"ok": True}), noop_sleep)
    resp = await client.request("GET", "/x", operation="op")
    assert resp.status_code == 200


async def test_5xx_retried_then_external_error(noop_sleep: SleepFn) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    client = _resilient(handler, noop_sleep, attempts=3)
    with pytest.raises(ExternalServiceError):
        await client.request("GET", "/x", operation="op")
    assert calls == 3  # все попытки исчерпаны


async def test_4xx_returned_not_retried(noop_sleep: SleepFn) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    client = _resilient(handler, noop_sleep)
    resp = await client.request("GET", "/x", operation="op")
    assert resp.status_code == 404
    assert calls == 1  # 4xx — не ретраим, breaker не «тропит»


async def test_transport_error_becomes_external_error(
    noop_sleep: SleepFn,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _resilient(handler, noop_sleep, attempts=2)
    with pytest.raises(ExternalServiceError):
        await client.request("GET", "/x", operation="op")


async def test_circuit_opens_and_rejects(noop_sleep: SleepFn) -> None:
    client = _resilient(lambda req: httpx.Response(500), noop_sleep, attempts=1, threshold=1)
    with pytest.raises(ExternalServiceError):
        await client.request("GET", "/x", operation="op")  # падение открывает breaker
    with pytest.raises(CircuitOpenError):
        await client.request("GET", "/x", operation="op")  # отклонено без сети


async def test_get_json_cache_aside(noop_sleep: SleepFn) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"v": calls})

    client = _resilient(handler, noop_sleep)
    cache = InMemoryCache(now=lambda: 0.0)
    first = await client.get_json(
        "/x", operation="op", cache=cache, cache_key="k", cache_ttl_seconds=60
    )
    second = await client.get_json(
        "/x", operation="op", cache=cache, cache_key="k", cache_ttl_seconds=60
    )
    assert first == second == {"v": 1}
    assert calls == 1  # второй вызов — из кеша


# --- HttpPlatformClient ---------------------------------------------------


def _platform(handler: Handler, sleep: SleepFn) -> HttpPlatformClient:
    return HttpPlatformClient(
        http_client=_resilient(handler, sleep, attempts=1),
        token_provider=StaticTokenProvider("tok"),
        cache=InMemoryCache(now=lambda: 0.0),
        cache_ttl_seconds=60,
    )


async def test_search_candidates_maps_and_authorizes(
    noop_sleep: SleepFn,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer tok"
        assert req.url.params["category"] == "CLEANING"
        assert req.url.params["group"] == "B"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "c-1",
                    "name": "Clean Co",
                    "category": "CLEANING",
                    "is_active": True,
                    "available": True,
                    "rating": 4.5,
                    "service_areas": ["msk"],
                    "channels": ["API"],
                }
            ],
        )

    client = _platform(handler, noop_sleep)
    out = await client.search_candidates(category="CLEANING", service_area="msk")
    assert len(out) == 1
    assert out[0].id == "c-1"
    assert out[0].rating == 4.5
    assert out[0].channels == ("API",)


async def test_search_candidates_degrades_to_empty_on_5xx(
    noop_sleep: SleepFn,
) -> None:
    client = _platform(lambda req: httpx.Response(503), noop_sleep)
    assert await client.search_candidates(category="CLEANING") == []


async def test_search_candidates_skips_malformed_item(
    noop_sleep: SleepFn,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "c-1",
                    "name": "A",
                    "category": "CLEANING",
                    "is_active": True,
                    "available": True,
                },
                {"bad": "item"},
            ],
        )

    out = await _platform(handler, noop_sleep).search_candidates(category="CLEANING")
    assert len(out) == 1
    assert out[0].id == "c-1"


async def test_search_candidates_non_array_degrades(
    noop_sleep: SleepFn,
) -> None:
    client = _platform(lambda req: httpx.Response(200, json={"not": "array"}), noop_sleep)
    assert await client.search_candidates(category="CLEANING") == []


async def test_search_candidates_degrades_on_404(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(404), noop_sleep)
    assert await client.search_candidates(category="CLEANING") == []


async def test_search_candidates_malformed_json_degrades(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(200, content=b"not json"), noop_sleep)
    assert await client.search_candidates(category="CLEANING") == []


async def test_create_service_order_maps_and_sends_idempotency_key(
    noop_sleep: SleepFn,
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.headers["authorization"] == "Bearer tok"
        assert req.headers["idempotency-key"] == "assign:r1"
        return httpx.Response(201, json={"id": "so-1", "status": "DRAFT"})

    client = _platform(handler, noop_sleep)
    ref = await client.create_service_order(
        request_id="r1", partner_id="c-1", category="CLEANING", idempotency_key="assign:r1"
    )
    assert ref is not None
    assert ref.id == "so-1"
    assert ref.status == "DRAFT"


async def test_create_service_order_degrades_on_5xx(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(503), noop_sleep)
    ref = await client.create_service_order(
        request_id="r1", partner_id="c-1", category="CLEANING", idempotency_key="k"
    )
    assert ref is None


async def test_create_service_order_malformed_json_degrades(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(201, content=b"nope"), noop_sleep)
    ref = await client.create_service_order(
        request_id="r1", partner_id="c-1", category="CLEANING", idempotency_key="k"
    )
    assert ref is None


async def test_get_partner_contact_maps(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path.endswith("/c-1/contact")
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"phone": "+79001112233", "email": "c@example.com"})

    contact = await _platform(handler, noop_sleep).get_partner_contact(partner_id="c-1")
    assert contact is not None
    assert contact.phone == "+79001112233"
    assert contact.email == "c@example.com"


async def test_get_partner_contact_degrades_on_404(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(404), noop_sleep)
    assert await client.get_partner_contact(partner_id="c-1") is None


async def test_get_partner_contact_degrades_on_5xx(noop_sleep: SleepFn) -> None:
    client = _platform(lambda req: httpx.Response(503), noop_sleep)
    assert await client.get_partner_contact(partner_id="c-1") is None


def test_factory_builds_resilient_client() -> None:
    from api.clients.factory import build_resilient_client
    from api.config import Settings

    http = httpx.AsyncClient(base_url="http://x")
    client = build_resilient_client("platform", http, Settings())
    assert isinstance(client, ResilientHttpClient)


async def test_search_candidates_cached(noop_sleep: SleepFn) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json=[
                {
                    "id": "c-1",
                    "name": "A",
                    "category": "CLEANING",
                    "is_active": True,
                    "available": True,
                }
            ],
        )

    client = _platform(handler, noop_sleep)
    await client.search_candidates(category="CLEANING")
    await client.search_candidates(category="CLEANING")
    assert calls == 1  # второй вызов — из кеша
