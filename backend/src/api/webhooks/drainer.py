"""Воркерный дрейн исходящих webhooks из outbox (E8, NFR-8)."""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.observability.logging import get_logger
from api.outbox.repository import OutboxRepository
from api.webhooks.client import WebhookDelivery
from api.webhooks.emitter import WEBHOOK_KIND

_logger = get_logger("webhooks.drain")


async def drain_webhook_batch(
    session: AsyncSession, client: WebhookDelivery, *, settings: Settings
) -> int:
    """Доставить пачку `webhook`-сообщений подписчику. Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(
        kind=WEBHOOK_KIND,
        now=now,
        limit=settings.outbox_batch_size,
        visibility_timeout=settings.outbox_visibility_timeout_seconds,
    )
    for message in batch:
        delay = settings.outbox_retry_base_seconds * (2 ** (message.attempts - 1))
        retry_at = now + datetime.timedelta(seconds=delay)
        try:
            delivered = await client.deliver(message.payload)
        except ExternalServiceError as exc:
            repo.mark_failed_or_retry(
                message,
                error=f"{type(exc).__name__}: {exc}",
                now=now,
                max_attempts=settings.outbox_max_attempts,
                retry_at=retry_at,
            )
            continue
        if delivered:
            repo.mark_done(message, now)
        else:
            # Подписчик ответил не-2xx — повтор с backoff (до исчерпания попыток).
            repo.mark_failed_or_retry(
                message,
                error="subscriber returned non-2xx",
                now=now,
                max_attempts=settings.outbox_max_attempts,
                retry_at=retry_at,
            )
    await session.commit()
    return len(batch)
