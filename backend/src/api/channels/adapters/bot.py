"""Каналы доставки в мессенджеры (§9.2, ADR-0004): Telegram / MAX Bot API.

«Разрабатываем сами»: общий `BotApiChannel` поверх `ResilientHttpClient` (без вендорских
SDK), Telegram и MAX — тонкие обёртки (одинаковая форма Bot API: `/bot<token>/sendMessage`).
MAX — `[ДОПУЩЕНИЕ §16.10]`: контракт по аналогии с Telegram, при расхождении правится
только этот адаптер. Токен бота — из конфига канала (ссылка на kb-vault), в URL-path.

В сообщение — только `DeliveryPayload` (минимальный состав по категории, FR-4.6): номер,
категория, маскированное описание. ПДн партнёру сверх разрешённого не уходят.
"""

from __future__ import annotations

from typing import Any

from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError

# Статус партнёра во входящем update → исход (E5).
_INBOUND_STATUS: dict[str, DeliveryOutcome] = {
    "accepted": DeliveryOutcome.ACK,
    "delivered": DeliveryOutcome.DELIVERED,
    "rejected": DeliveryOutcome.FAILED,
    "failed": DeliveryOutcome.FAILED,
}


def _format_message(payload: DeliveryPayload) -> str:
    """Текст партнёру (без ПДн): номер, категория, маскированное описание."""
    lines = [f"Новая заявка {payload.number}", f"Категория: {payload.category}", payload.summary]
    return "\n".join(line for line in lines if line)


class BotApiChannel:
    """Общая реализация Bot API (Telegram/MAX). `channel_type` задаёт обёртка."""

    def __init__(self, http: ResilientHttpClient, *, channel_type: ChannelType) -> None:
        self._http = http
        self.channel_type = channel_type

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        token = str(config.config.get("bot_token", ""))
        chat_id = config.config.get("chat_id")
        if not token or not chat_id:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "missing_bot_config"}
            )
        body = {"chat_id": chat_id, "text": _format_message(payload)}
        try:
            response = await self._http.request(
                "POST", f"/bot{token}/sendMessage", operation="deliver", json=body
            )
        except ExternalServiceError as exc:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        if response.status_code >= 400:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"status": response.status_code}
            )
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT,
            provider_response={"status": response.status_code},
            external_ref=_message_ref(response),
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        ref = payload.get("request_ref") or payload.get("external_ref")
        status = payload.get("status")
        if ref is None or not isinstance(status, str):
            return None
        outcome = _INBOUND_STATUS.get(status.lower())
        if outcome is None:
            return None
        return StatusUpdate(request_ref=str(ref), outcome=outcome, raw=payload)

    async def healthcheck(self, config: ChannelConfig) -> Health:
        token = str(config.config.get("bot_token", ""))
        if not token:
            return Health(status=HealthStatus.UNHEALTHY, detail="missing bot_token")
        try:
            response = await self._http.request(
                "GET", f"/bot{token}/getMe", operation="healthcheck"
            )
        except ExternalServiceError:
            return Health(status=HealthStatus.UNHEALTHY, detail="unreachable")
        if response.status_code >= 400:
            return Health(status=HealthStatus.DEGRADED, detail=f"status={response.status_code}")
        return Health(status=HealthStatus.HEALTHY)


class TelegramChannel(BotApiChannel):
    """Telegram Bot API."""

    def __init__(self, http: ResilientHttpClient) -> None:
        super().__init__(http, channel_type=ChannelType.TELEGRAM)


class MaxChannel(BotApiChannel):
    """MAX Bot API `[ДОПУЩЕНИЕ §16.10]` — форма по аналогии с Telegram."""

    def __init__(self, http: ResilientHttpClient) -> None:
        super().__init__(http, channel_type=ChannelType.MAX)


def _message_ref(response: Any) -> str | None:
    """Внешняя ссылка на сообщение (Telegram: result.message_id)."""
    try:
        data = response.json()
    except ValueError:
        return None
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        ref = data["result"].get("message_id")
        return str(ref) if ref is not None else None
    return None
