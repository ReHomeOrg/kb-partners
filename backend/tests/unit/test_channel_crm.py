"""Юнит-тесты CRM-каналов Bitrix24/amoCRM (E4, §9.2, ADR-0004) — без сети."""

from __future__ import annotations

import httpx

from api.channels.adapters.crm import AmoCrmChannel, Bitrix24Channel
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import ChannelConfig, DeliveryPayload
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy


def _resilient(handler: object) -> ResilientHttpClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="http://crm.example",
    )
    return ResilientHttpClient(
        client_name="crm",
        http=http,
        breaker=CircuitBreaker(failure_threshold=3, reset_timeout=1.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1, base_delay=0.0, max_delay=0.0),
    )


def _payload() -> DeliveryPayload:
    return DeliveryPayload(
        request_id="r1",
        number="RQ-1",
        category="CLEANING",
        summary="уборка",
        params={},
        idempotency_key="dispatch:r1:1",
    )


def _config(**cfg: object) -> ChannelConfig:
    return ChannelConfig(
        collaborator_id="c-1", channel_type=ChannelType.CRM, priority=10, config=dict(cfg)
    )


async def test_bitrix_creates_lead() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/1/tok/crm.lead.add.json"
        assert "RQ-1" in request.content.decode()
        return httpx.Response(200, json={"result": 555})

    channel = Bitrix24Channel(_resilient(handler))
    result = await channel.deliver(_payload(), _config(webhook_path="/rest/1/tok/"))
    assert result.outcome is DeliveryOutcome.SENT
    assert result.external_ref == "555"


async def test_bitrix_missing_webhook_fails() -> None:
    result = await Bitrix24Channel(_resilient(lambda r: httpx.Response(200))).deliver(
        _payload(), _config()
    )
    assert result.outcome is DeliveryOutcome.FAILED
    assert result.provider_response["error"] == "missing_webhook"


async def test_amocrm_creates_lead_with_bearer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/leads"
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"_embedded": {"leads": [{"id": 1}]}})

    result = await AmoCrmChannel(_resilient(handler)).deliver(
        _payload(), _config(access_token="tok")
    )
    assert result.outcome is DeliveryOutcome.SENT


async def test_amocrm_missing_token_fails() -> None:
    result = await AmoCrmChannel(_resilient(lambda r: httpx.Response(200))).deliver(
        _payload(), _config()
    )
    assert result.outcome is DeliveryOutcome.FAILED


async def test_amocrm_http_error_fails() -> None:
    result = await AmoCrmChannel(_resilient(lambda r: httpx.Response(401))).deliver(
        _payload(), _config(access_token="tok")
    )
    assert result.outcome is DeliveryOutcome.FAILED


async def test_crm_parse_inbound() -> None:
    update = await Bitrix24Channel(_resilient(lambda r: httpx.Response(200))).parse_inbound(
        {"request_ref": "r1", "status": "delivered"}, _config()
    )
    assert update is not None and update.outcome is DeliveryOutcome.DELIVERED


async def test_bitrix_healthcheck() -> None:
    channel = Bitrix24Channel(_resilient(lambda r: httpx.Response(200, json={"result": {}})))
    health = await channel.healthcheck(_config(webhook_path="/rest/1/tok/"))
    assert health.status is HealthStatus.HEALTHY
