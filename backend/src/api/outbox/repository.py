"""Доступ к transactional outbox (NFR-8): enqueue, claim, завершение/повтор."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.outbox.models import OutboxMessage, OutboxStatus

_MAX_ERROR_LEN = 1000


class OutboxRepository:
    """Репозиторий outbox-сообщений."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def enqueue(self, kind: str, payload: dict[str, object]) -> OutboxMessage:
        """Поставить сообщение в outbox (в текущей транзакции продюсера)."""
        message = OutboxMessage(kind=kind, payload=payload, status=OutboxStatus.PENDING)
        self._session.add(message)
        return message

    async def get_for_update(self, message_id: uuid.UUID) -> OutboxMessage | None:
        stmt = select(OutboxMessage).where(OutboxMessage.id == message_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def claim_batch(
        self,
        *,
        kind: str,
        now: datetime.datetime,
        limit: int,
        visibility_timeout: float = 300.0,
    ) -> list[OutboxMessage]:
        """Захватить готовые сообщения (FOR UPDATE SKIP LOCKED).

        Берёт PENDING, а также PROCESSING с истёкшим visibility-окном (reclaim
        осиротевших после сбоя воркера). Помечает PROCESSING, инкрементит attempts и
        сдвигает `available_at` на visibility_timeout — конкурентные воркеры не
        пересекаются (single-delivery в пределах окна).
        """
        stmt = (
            select(OutboxMessage)
            .where(
                OutboxMessage.kind == kind,
                OutboxMessage.status.in_([OutboxStatus.PENDING, OutboxStatus.PROCESSING]),
                OutboxMessage.available_at <= now,
            )
            .order_by(OutboxMessage.available_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        reclaim_at = now + datetime.timedelta(seconds=visibility_timeout)
        for row in rows:
            row.status = OutboxStatus.PROCESSING
            row.attempts += 1
            row.available_at = reclaim_at
        return rows

    @staticmethod
    def mark_done(message: OutboxMessage, now: datetime.datetime) -> None:
        message.status = OutboxStatus.DONE
        message.processed_at = now

    @staticmethod
    def mark_failed_or_retry(
        message: OutboxMessage,
        *,
        error: str,
        now: datetime.datetime,
        max_attempts: int,
        retry_at: datetime.datetime,
    ) -> None:
        """Повтор с backoff, либо терминальный FAILED при исчерпании попыток."""
        message.last_error = error[:_MAX_ERROR_LEN]
        if message.attempts >= max_attempts:
            message.status = OutboxStatus.FAILED
            message.processed_at = now
        else:
            message.status = OutboxStatus.PENDING
            message.available_at = retry_at
