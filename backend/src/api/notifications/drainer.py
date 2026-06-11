"""Воркерный дрейн уведомлений из outbox (E8, NFR-8): резолв контакта + веер каналов.

Для каждого `notification`-сообщения: резолвим контакт адресата (ПДн, на дрейне, не в
outbox), затем best-effort веер push/SMS/email по доступным контактам. Сбой одного
канала не валит прочие. Недоступность боевого канала (ExternalServiceError) → backoff-
повтор всего сообщения (как в webhooks-дрейнере); прочие сбои канала изолированы.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.notifications.channels import (
    NotificationNotice,
    Recipient,
    send_email,
    send_push,
    send_sms,
)
from api.notifications.contacts import ContactResolver
from api.notifications.emitter import NOTIFICATION_KIND
from api.notifications.events import NotifyAudience
from api.observability.logging import get_logger
from api.outbox.models import OutboxMessage
from api.outbox.repository import OutboxRepository

_logger = get_logger("notifications.drain")


def _notice(payload: dict[str, object]) -> NotificationNotice | None:
    """Собрать DTO из payload; некорректный — отбрасываем (закрываем сообщение)."""
    try:
        return NotificationNotice(
            request_id=uuid.UUID(str(payload["request_id"])),
            number=str(payload["number"]),
            audience=NotifyAudience(str(payload["audience"])),
            summary=str(payload["summary"]),
            requester_id=_opt(payload.get("requester_id")),
            partner_id=_opt(payload.get("partner_id")),
        )
    except (KeyError, ValueError):
        return None


def _opt(value: object) -> str | None:
    return str(value) if value else None


async def deliver_notification(
    notice: NotificationNotice, recipient: Recipient, settings: Settings
) -> int:
    """Веер уведомления по каналам для известных контактов. Возвращает число попыток.

    `ExternalServiceError` (боевой канал недоступен) пробрасывается → backoff-повтор;
    прочие сбои канала изолированы (best-effort).
    """
    attempted = 0
    # SMS — по телефону; ExternalServiceError всплывает наверх (повтор сообщения).
    if await send_sms(notice, recipient.phone, settings):
        attempted += 1
    # Email — best-effort (SMTP-сбои уже изолированы внутри send_email → False).
    if await send_email(notice, recipient.email, settings):
        attempted += 1
    # Push — seam (web-push M11), без ПДн-контакта.
    if send_push(notice, settings):
        attempted += 1
    return attempted


async def drain_notification_batch(
    session: AsyncSession, *, settings: Settings, resolver: ContactResolver
) -> int:
    """Воркерный дрейн пачки PENDING `notification`-сообщений. Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(
        kind=NOTIFICATION_KIND,
        now=now,
        limit=settings.outbox_batch_size,
        visibility_timeout=settings.outbox_visibility_timeout_seconds,
    )
    for message in batch:
        await _drain_one(repo, message, settings=settings, resolver=resolver, now=now)
    await session.commit()
    return len(batch)


async def _drain_one(
    repo: OutboxRepository,
    message: OutboxMessage,
    *,
    settings: Settings,
    resolver: ContactResolver,
    now: datetime.datetime,
) -> None:
    notice = _notice(message.payload)
    if notice is None:
        repo.mark_done(message, now)  # битый payload — ретраить нечего
        return
    try:
        recipient = await resolver.resolve(notice)
        attempted = await deliver_notification(notice, recipient, settings)
    except ExternalServiceError as exc:  # боевой канал/сосед недоступен → backoff-повтор
        delay = settings.outbox_retry_base_seconds * (2 ** (message.attempts - 1))
        repo.mark_failed_or_retry(
            message,
            error=f"{type(exc).__name__}: {exc}",
            now=now,
            max_attempts=settings.outbox_max_attempts,
            retry_at=now + datetime.timedelta(seconds=delay),
        )
        return
    repo.mark_done(message, now)
    _logger.info(
        "notification drained: number=%s audience=%s channels=%d",
        notice.number,
        notice.audience.value,
        attempted,
    )
