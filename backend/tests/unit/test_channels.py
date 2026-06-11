"""Юнит-тесты адаптеров каналов доставки (§9.2): Mock и PartnerApi (MockTransport)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest

from api.channels.adapters.mock import MockChannel
from api.channels.adapters.partner_api import PartnerApiChannel
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import ChannelConfig, DeliveryPayload
from api.clients.auth import StaticTokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]
SleepFn = Callable[[float], Awaitable[None]]


@pytest.fixture
def noop_sleep() -> SleepFn:
    async def _sleep(_seconds: float) -> None:
        return None

    return _sleep


def _payload() -> DeliveryPayload:
    return DeliveryPayload(
        request_id="r1",
        number="RQ-1",
        category="CLEANING",
        summary="уборка 50 м2",
        params={"area_sqm": 50},
        idempotency_key="deliver:r1:1",
    )


def _config(channel_type: ChannelType, **config: object) -> ChannelConfig:
    return ChannelConfig(
        collaborator_id="c-1", channel_type=channel_type, priority=1, config=dict(config)
    )


def _partner_channel(handler: Handler, sleep: SleepFn) -> PartnerApiChannel:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://partner")
    resilient = ResilientHttpClient(
        client_name="partner_api",
        http=http,
        breaker=CircuitBreaker(failure_threshold=5, reset_timeout=30, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1),
        sleep=sleep,
        monotonic=lambda: 0.0,
    )
    return PartnerApiChannel(resilient, StaticTokenProvider("tok"))


# --- MockChannel ----------------------------------------------------------


async def test_mock_delivers_and_records() -> None:
    channel = MockChannel()
    result = await channel.deliver(_payload(), _config(ChannelType.MOCK))
    assert result.outcome is DeliveryOutcome.SENT
    assert result.external_ref == "mock:r1"
    assert len(channel.delivered) == 1


async def test_mock_parse_inbound() -> None:
    channel = MockChannel()
    update = await channel.parse_inbound(
        {"request_ref": "r1", "outcome": "ACK"}, _config(ChannelType.MOCK)
    )
    assert update is not None
    assert update.outcome is DeliveryOutcome.ACK
    assert await channel.parse_inbound({}, _config(ChannelType.MOCK)) is None
    # Невалидный исход → None (не падаем).
    assert (
        await channel.parse_inbound(
            {"request_ref": "r1", "outcome": "BADVALUE"}, _config(ChannelType.MOCK)
        )
        is None
    )


async def test_mock_healthcheck() -> None:
    health = await MockChannel().healthcheck(_config(ChannelType.MOCK))
    assert health.status is HealthStatus.HEALTHY


# --- PartnerApiChannel ----------------------------------------------------


async def test_partner_api_deliver_success(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert req.url.path == "/orders"
        assert req.headers["idempotency-key"] == "deliver:r1:1"
        assert req.headers["authorization"] == "Bearer tok"
        return httpx.Response(201, json={"external_ref": "ext-9"})

    channel = _partner_channel(handler, noop_sleep)
    result = await channel.deliver(_payload(), _config(ChannelType.API))
    assert result.outcome is DeliveryOutcome.SENT
    assert result.external_ref == "ext-9"
    assert "summary" not in result.provider_response  # ПДн/тело не эхоится


async def test_partner_api_deliver_non_json_body_sent_without_ref(noop_sleep: SleepFn) -> None:
    channel = _partner_channel(lambda req: httpx.Response(200, content=b"OK"), noop_sleep)
    result = await channel.deliver(_payload(), _config(ChannelType.API))
    assert result.outcome is DeliveryOutcome.SENT
    assert result.external_ref is None


async def test_partner_api_deliver_4xx_is_failed(noop_sleep: SleepFn) -> None:
    channel = _partner_channel(lambda req: httpx.Response(422), noop_sleep)
    result = await channel.deliver(_payload(), _config(ChannelType.API))
    assert result.outcome is DeliveryOutcome.FAILED
    assert result.provider_response["status"] == 422


async def test_partner_api_deliver_unreachable_is_failed(noop_sleep: SleepFn) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    channel = _partner_channel(handler, noop_sleep)
    result = await channel.deliver(_payload(), _config(ChannelType.API))
    assert result.outcome is DeliveryOutcome.FAILED


async def test_partner_api_parse_inbound_maps_status(noop_sleep: SleepFn) -> None:
    channel = _partner_channel(lambda req: httpx.Response(200), noop_sleep)
    update = await channel.parse_inbound(
        {"external_ref": "ext-9", "status": "accepted"}, _config(ChannelType.API)
    )
    assert update is not None
    assert update.outcome is DeliveryOutcome.ACK
    assert update.request_ref == "ext-9"


async def test_partner_api_parse_inbound_unknown_status_none(noop_sleep: SleepFn) -> None:
    channel = _partner_channel(lambda req: httpx.Response(200), noop_sleep)
    assert (
        await channel.parse_inbound(
            {"external_ref": "x", "status": "weird"}, _config(ChannelType.API)
        )
        is None
    )
    assert await channel.parse_inbound({"status": "accepted"}, _config(ChannelType.API)) is None


async def test_partner_api_healthcheck(noop_sleep: SleepFn) -> None:
    healthy = await _partner_channel(lambda req: httpx.Response(200), noop_sleep).healthcheck(
        _config(ChannelType.API)
    )
    assert healthy.status is HealthStatus.HEALTHY
    degraded = await _partner_channel(lambda req: httpx.Response(503), noop_sleep).healthcheck(
        _config(ChannelType.API)
    )
    # 503 → ResilientHttpClient ретраит и бросает ExternalServiceError → UNHEALTHY.
    assert degraded.status is HealthStatus.UNHEALTHY
