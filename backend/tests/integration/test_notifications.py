"""Интеграционные тесты уведомлений (E8): эмиссия в outbox + воркерный дрейн."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.notifications import emitter
from api.notifications.contacts import NullContactResolver
from api.notifications.drainer import drain_notification_batch
from api.notifications.emitter import NOTIFICATION_KIND, emit_notifications
from api.outbox.models import OutboxMessage, OutboxStatus
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus

_RESOLVER = NullContactResolver()


async def _count(session: AsyncSession, status: OutboxStatus | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.kind == NOTIFICATION_KIND)
    )
    if status is not None:
        stmt = stmt.where(OutboxMessage.status == status)
    return int((await session.execute(stmt)).scalar_one())


async def test_emit_noop_when_disabled(session: AsyncSession) -> None:
    # Дефолт notifications_enabled=False → ничего не ставится в outbox.
    emit_notifications(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.ASSIGNED,
        requester_id="u-1",
    )
    await session.commit()
    assert await _count(session) == 0


async def test_emit_enqueues_per_audience(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emitter, "get_settings", lambda: Settings(notifications_enabled=True))
    # CANCELLED уведомляет двух адресатов (заявитель + партнёр) → две строки (partner_id задан).
    emit_notifications(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.CANCELLED,
        requester_id="u-1",
        partner_id="c-1",
    )
    await session.commit()
    assert await _count(session) == 2


async def test_emit_skips_partner_without_partner_id(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emitter, "get_settings", lambda: Settings(notifications_enabled=True))
    # CANCELLED без partner_id → только заявитель (партнёра некого уведомлять).
    emit_notifications(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.CANCELLED,
        requester_id="u-1",
    )
    await session.commit()
    assert await _count(session) == 1


async def test_drain_marks_done(session: AsyncSession) -> None:
    OutboxRepository(session).enqueue(
        NOTIFICATION_KIND,
        {
            "audience": "user",
            "request_id": str(uuid.uuid4()),
            "number": "RQ-1",
            "status": "ASSIGNED",
            "summary": "Партнёр назначен",
        },
    )
    await session.commit()
    processed = await drain_notification_batch(session, settings=Settings(), resolver=_RESOLVER)
    assert processed == 1
    assert await _count(session, OutboxStatus.DONE) == 1


async def test_drain_closes_broken_payload(session: AsyncSession) -> None:
    OutboxRepository(session).enqueue(NOTIFICATION_KIND, {"oops": "no fields"})
    await session.commit()
    await drain_notification_batch(session, settings=Settings(), resolver=_RESOLVER)
    # Битый payload не ретраится — закрывается DONE.
    assert await _count(session, OutboxStatus.DONE) == 1
