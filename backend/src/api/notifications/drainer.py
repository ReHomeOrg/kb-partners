"""Воркерный дрейн уведомлений из outbox (E8, NFR-8): резолв контакта + веер каналов.

Для каждого `notification`-сообщения: резолвим контакт адресата (телефон/email — ПДн,
на дрейне, не в outbox) + грузим web-push подписки владельца, затем best-effort веер
SMS/email/web-push. Сбой одного канала не валит прочие. Недоступность боевого канала
(ExternalServiceError) → backoff-повтор всего сообщения. Истёкшая web-push подписка
(404/410) удаляется.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.notifications.channels import NotificationNotice, Recipient, send_email, send_sms
from api.notifications.contacts import ContactResolver
from api.notifications.emitter import NOTIFICATION_KIND
from api.notifications.events import NotifyAudience
from api.observability.logging import get_logger
from api.outbox.models import OutboxMessage
from api.outbox.repository import OutboxRepository
from api.push.repository import PushSubscriptionRepository
from api.push.webpush import SubscriptionExpired, send_webpush

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


def _push_owner(notice: NotificationNotice) -> str | None:
    """Владелец web-push подписок для адресата (заявитель/партнёр). Оператор — без push."""
    if notice.audience is NotifyAudience.USER:
        return notice.requester_id
    if notice.audience is NotifyAudience.PARTNER:
        return notice.partner_id
    return None


async def _deliver_push(
    session: AsyncSession, notice: NotificationNotice, settings: Settings
) -> int:
    """Web-push по подпискам владельца. Истёкшие (404/410) удаляет. Возвращает число доставок."""
    if not settings.vapid_private_key:
        return 0
    owner_id = _push_owner(notice)
    if owner_id is None:
        return 0
    repo = PushSubscriptionRepository(session)
    delivered = 0
    for sub in await repo.list_for_owner(owner_id):
        try:
            if await send_webpush(
                sub, number=notice.number, summary=notice.summary, settings=settings
            ):
                delivered += 1
        except SubscriptionExpired:
            await repo.delete(owner_id=owner_id, endpoint=sub.endpoint)
    return delivered


async def deliver_notification(
    session: AsyncSession, notice: NotificationNotice, recipient: Recipient, settings: Settings
) -> int:
    """Веер уведомления (SMS/email/web-push) по известным контактам/подпискам.

    `ExternalServiceError` (боевой канал недоступен) пробрасывается → backoff-повтор;
    прочие сбои канала изолированы (best-effort).
    """
    attempted = 0
    if await send_sms(notice, recipient.phone, settings):
        attempted += 1
    if await send_email(notice, recipient.email, settings):
        attempted += 1
    attempted += await _deliver_push(session, notice, settings)
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
        await _drain_one(session, repo, message, settings=settings, resolver=resolver, now=now)
    await session.commit()
    return len(batch)


async def _drain_one(
    session: AsyncSession,
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
        attempted = await deliver_notification(session, notice, recipient, settings)
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
