"""EmailChannel (§9.2, ADR-0004) — доставка заявки партнёру письмом (SMTP).

«Разрабатываем сами»: исходящее — stdlib `smtplib` (STARTTLS) в `asyncio.to_thread`
(не блокируем loop), без вендорского SDK. Адрес партнёра — в config канала; SMTP-креды —
из настроек (ссылка на kb-vault). В тело — только `DeliveryPayload` (минимальный состав
по категории, FR-4.6), без сырых ПДн.

Входящее (E5): `parse_inbound` мапит уже разобранное письмо (IMAP-парсер — отдельный
inbound-транспорт) `{request_ref, status}` → `StatusUpdate`.
"""

from __future__ import annotations

import asyncio
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import Any

from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.config import Settings
from api.observability.logging import get_logger

_logger = get_logger("channels.email")

SmtpSender = Callable[[EmailMessage, Settings], None]

_INBOUND_STATUS: dict[str, DeliveryOutcome] = {
    "accepted": DeliveryOutcome.ACK,
    "delivered": DeliveryOutcome.DELIVERED,
    "rejected": DeliveryOutcome.FAILED,
    "failed": DeliveryOutcome.FAILED,
}


def _default_smtp_send(message: EmailMessage, settings: Settings) -> None:
    """Блокирующая SMTP-отправка (STARTTLS). Через asyncio.to_thread."""
    with smtplib.SMTP(settings.notify_smtp_host, settings.notify_smtp_port, timeout=10) as server:
        server.starttls()
        if settings.notify_smtp_user:
            server.login(settings.notify_smtp_user, settings.notify_smtp_password)
        server.send_message(message)


def _build_message(payload: DeliveryPayload, to_addr: str, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.notify_email_from
    message["To"] = to_addr
    message["Subject"] = f"Новая заявка {payload.number} [{payload.category}]"
    body = "\n".join(
        [
            f"Заявка: {payload.number}",
            f"Категория: {payload.category}",
            f"Описание: {payload.summary}",
            f"Идемпотентность: {payload.idempotency_key}",
        ]
    )
    message.set_content(body)
    return message


class EmailChannel:
    """Канал доставки письмом (SMTP). `sender` инъектируется в тестах (без сети)."""

    channel_type = ChannelType.EMAIL

    def __init__(self, settings: Settings, *, sender: SmtpSender | None = None) -> None:
        self._settings = settings
        self._sender = sender or _default_smtp_send

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        to_addr = str(config.config.get("email", ""))
        if (
            not self._settings.notify_smtp_host
            or not self._settings.notify_email_from
            or not to_addr
        ):
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "missing_email_config"}
            )
        message = _build_message(payload, to_addr, self._settings)
        try:
            await asyncio.to_thread(self._sender, message, self._settings)
        except (smtplib.SMTPException, OSError) as exc:
            _logger.warning(
                "email deliver degraded: %s number=%s", type(exc).__name__, payload.number
            )
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        return DeliveryResult(outcome=DeliveryOutcome.SENT, provider_response={"status": "sent"})

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
        if not self._settings.notify_smtp_host or not self._settings.notify_email_from:
            return Health(status=HealthStatus.UNHEALTHY, detail="smtp not configured")
        return Health(status=HealthStatus.HEALTHY)
