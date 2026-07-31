"""Воркерный дрейн колбэков смены статуса в Консьерж из outbox (E9, U3, NFR-8)."""

from __future__ import annotations

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.callback import CONCIERGE_CALLBACK_KIND
from api.clients.concierge import ConciergeClient
from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.observability.logging import get_logger
from api.outbox.repository import OutboxRepository

_logger = get_logger("agent.concierge.drain")


async def drain_concierge_callback_batch(
    session: AsyncSession, client: ConciergeClient, *, settings: Settings
) -> int:
    """Доставить пачку `concierge_status`-колбэков Консьержу. Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(
        kind=CONCIERGE_CALLBACK_KIND,
        now=now,
        limit=settings.outbox_batch_size,
        visibility_timeout=settings.outbox_visibility_timeout_seconds,
    )
    for message in batch:
        delay = settings.outbox_retry_base_seconds * (2 ** (message.attempts - 1))
        retry_at = now + datetime.timedelta(seconds=delay)
        try:
            delivered = await client.deliver_status_update(message.payload)
        except ExternalServiceError as exc:  # Консьерж недоступен → backoff-повтор
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
            # Консьерж ответил не-2xx — повтор с backoff (до исчерпания попыток).
            repo.mark_failed_or_retry(
                message,
                error="concierge returned non-2xx",
                now=now,
                max_attempts=settings.outbox_max_attempts,
                retry_at=retry_at,
            )
    await session.commit()
    return len(batch)
