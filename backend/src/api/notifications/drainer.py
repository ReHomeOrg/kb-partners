"""Воркерный дрейн уведомлений из outbox (E8, NFR-8): веер по seam-каналам.

Для каждого `notification`-сообщения — best-effort веер push/SMS/email (config-gated
seam'ы). Сбой одного канала не валит прочие. Seam'ы исключений не бросают, поэтому
сообщение всегда закрывается DONE; боевые каналы (после ADR) при сбое провайдера
смогут поднимать ExternalServiceError → backoff-повтор (как в webhooks-дрейнере).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.notifications.channels import NotificationNotice, maybe_email, maybe_push, maybe_sms
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
        )
    except (KeyError, ValueError):
        return None


def deliver_notification(notice: NotificationNotice, settings: Settings) -> int:
    """Веер уведомления по seam-каналам. Возвращает число каналов, выполнивших попытку."""
    attempted = 0
    for name, channel in (("push", maybe_push), ("sms", maybe_sms), ("email", maybe_email)):
        try:
            if channel(notice, settings):
                attempted += 1
        except Exception:  # noqa: BLE001 — изоляция канала: один сбой не валит прочие
            _logger.warning("notification channel failed: %s number=%s", name, notice.number)
    return attempted


async def drain_notification_batch(session: AsyncSession, *, settings: Settings) -> int:
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
        _drain_one(repo, message, settings=settings, now=now)
    await session.commit()
    return len(batch)


def _drain_one(
    repo: OutboxRepository,
    message: OutboxMessage,
    *,
    settings: Settings,
    now: datetime.datetime,
) -> None:
    notice = _notice(message.payload)
    if notice is None:
        repo.mark_done(message, now)  # битый payload — ретраить нечего
        return
    try:
        attempted = deliver_notification(notice, settings)
    except ExternalServiceError as exc:  # боевой канал недоступен → backoff-повтор
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
