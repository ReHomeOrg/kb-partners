"""Юнит-тесты Bot API-каналов Telegram/MAX (E4, §9.2, ADR-0004) — без сети."""

from __future__ import annotations

import httpx

from api.channels.adapters.bot import MaxChannel, TelegramChannel
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import ChannelConfig, DeliveryPayload
from api.clients.base import ResilientHttpClient
from api.clients.circuit_breaker import CircuitBreaker
from api.clients.retry import RetryPolicy


def _resilient(handler: object, name: str = "telegram") -> ResilientHttpClient:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        base_url="https://api.telegram.org",
    )
    return ResilientHttpClient(
        client_name=name,
        http=http,
        breaker=CircuitBreaker(failure_threshold=3, reset_timeout=1.0, now=lambda: 0.0),
        retry=RetryPolicy(attempts=1, base_delay=0.0, max_delay=0.0),
    )


def _config(**extra: object) -> ChannelConfig:
    cfg: dict[str, object] = {"bot_token": "T:123", "chat_id": "42", **extra}
    return ChannelConfig(
        collaborator_id="c-1", channel_type=ChannelType.TELEGRAM, priority=10, config=cfg
    )


def _payload() -> DeliveryPayload:
    return DeliveryPayload(
        request_id="r1",
        number="RQ-1",
        category="CLEANING",
        summary="уборка 2 комнаты",
        params={},
        idempotency_key="dispatch:r1:1",
    )


async def test_telegram_deliver_sends_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botT:123/sendMessage"
        body = request.content.decode()
        assert "RQ-1" in body and "42" in body
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 777}})

    result = await TelegramChannel(_resilient(handler)).deliver(_payload(), _config())
    assert result.outcome is DeliveryOutcome.SENT
    assert result.external_ref == "777"


async def test_deliver_missing_bot_config_fails() -> None:
    cfg = ChannelConfig(
        collaborator_id="c-1", channel_type=ChannelType.TELEGRAM, priority=10, config={}
    )
    result = await TelegramChannel(_resilient(lambda r: httpx.Response(200))).deliver(
        _payload(), cfg
    )
    assert result.outcome is DeliveryOutcome.FAILED
    assert result.provider_response["error"] == "missing_bot_config"


async def test_deliver_http_error_fails() -> None:
    result = await TelegramChannel(_resilient(lambda r: httpx.Response(403))).deliver(
        _payload(), _config()
    )
    assert result.outcome is DeliveryOutcome.FAILED


async def test_healthcheck_get_me() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/botT:123/getMe"
        return httpx.Response(200, json={"ok": True})

    health = await TelegramChannel(_resilient(handler)).healthcheck(_config())
    assert health.status is HealthStatus.HEALTHY


async def test_parse_inbound_maps_status() -> None:
    channel = MaxChannel(_resilient(lambda r: httpx.Response(200)))
    update = await channel.parse_inbound({"request_ref": "r1", "status": "accepted"}, _config())
    assert update is not None
    assert update.request_ref == "r1"
    assert update.outcome is DeliveryOutcome.ACK


async def test_max_channel_type() -> None:
    assert MaxChannel(_resilient(lambda r: httpx.Response(200))).channel_type is ChannelType.MAX
