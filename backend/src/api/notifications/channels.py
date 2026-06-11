"""Боевые каналы уведомлений push/SMS/email (E8, FR-8.1/8.2, ADR-0004).

«Разрабатываем сами»: SMS — свой HTTP-адаптер SMS.ru на ResilientHttpClient; email —
SMTP (stdlib `smtplib` в треде, чтобы не блокировать event loop); push — web-push
(VAPID) — seam до M11 (нужен store подписок + SW портала). Каждый канал config-gated
(пустой креденшл → инертен) и best-effort: возвращает «доставлено/попытка?»,
ExternalServiceError пробрасывается дрейнеру (backoff-повтор), прочие сбои → False+WARN.

ФЗ-152: контакт адресата (ПДн) приходит резолвером и в логи НЕ пишется; в тело идёт
только номер заявки + нейтральная RU-сводка (без ПДн).
"""

from __future__ import annotations

import asyncio
import smtplib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from api.clients.factory import build_resilient_client
from api.config import Settings
from api.notifications.events import NotifyAudience
from api.observability.logging import get_logger

_logger = get_logger("notifications.channels")

SmtpSender = Callable[[EmailMessage, Settings], None]


@dataclass(frozen=True)
class NotificationNotice:
    """Плоский DTO уведомления — только не-ПДн значения + непрозрачные ссылки."""

    request_id: uuid.UUID
    number: str
    audience: NotifyAudience
    summary: str  # нейтральная RU-сводка, без ПДн
    requester_id: str | None = None
    partner_id: str | None = None


@dataclass(frozen=True)
class Recipient:
    """Контакт адресата (ПДн), резолвится на дрейне; в outbox/логи не попадает."""

    phone: str | None = None
    email: str | None = None


def _message_text(notice: NotificationNotice) -> str:
    """Тело уведомления — без ПДн (номер заявки + сводка статуса)."""
    return f"Заявка {notice.number}: {notice.summary}"


async def send_sms(
    notice: NotificationNotice,
    phone: str | None,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """SMS через SMS.ru (`/sms/send`, json=1). Инертно без api_id/телефона."""
    if not settings.sms_ru_api_id or not phone:
        return False
    async with httpx.AsyncClient(
        base_url=settings.sms_ru_api_base_url,
        timeout=settings.client_timeout_seconds,
        transport=transport,
    ) as http:
        client = build_resilient_client("sms_ru", http, settings)
        response = await client.request(
            "POST",
            "/sms/send",
            operation="send_sms",
            params={
                "api_id": settings.sms_ru_api_id,
                "to": phone,
                "msg": _message_text(notice),
                "json": 1,
            },
        )
    if response.status_code >= 400:
        _logger.warning("sms.ru degraded: status=%d number=%s", response.status_code, notice.number)
        return False
    try:
        ok = str(response.json().get("status")) == "OK"
    except (ValueError, AttributeError):
        _logger.warning("sms.ru degraded: malformed JSON number=%s", notice.number)
        return False
    return ok


def _default_smtp_send(message: EmailMessage, settings: Settings) -> None:
    """Блокирующая SMTP-отправка (STARTTLS). Вызывается через asyncio.to_thread."""
    with smtplib.SMTP(settings.notify_smtp_host, settings.notify_smtp_port, timeout=10) as server:
        server.starttls()
        if settings.notify_smtp_user:
            server.login(settings.notify_smtp_user, settings.notify_smtp_password)
        server.send_message(message)


async def send_email(
    notice: NotificationNotice,
    to_addr: str | None,
    settings: Settings,
    *,
    sender: SmtpSender | None = None,
) -> bool:
    """Email через SMTP (РФ). Инертно без smtp_host/from/адреса. Best-effort."""
    if not settings.notify_smtp_host or not settings.notify_email_from or not to_addr:
        return False
    message = EmailMessage()
    message["From"] = settings.notify_email_from
    message["To"] = to_addr
    message["Subject"] = f"Заявка {notice.number}: {notice.summary}"
    message.set_content(_message_text(notice))
    smtp_send = sender or _default_smtp_send
    try:
        await asyncio.to_thread(smtp_send, message, settings)
    except (smtplib.SMTPException, OSError) as exc:
        _logger.warning("smtp degraded: %s number=%s", type(exc).__name__, notice.number)
        return False
    return True


def send_push(notice: NotificationNotice, settings: Settings) -> bool:
    """Web-push (VAPID) — seam до M11 (нужен store подписок + SW портала)."""
    if not settings.notify_push_token:
        return False
    _logger.info("push notification pending web-push (M11): number=%s", notice.number)
    return True
