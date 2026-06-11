"""Интеграционные тесты исходящих webhooks (E8): эмиссия в outbox + воркерный дрейн."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.outbox.models import OutboxMessage, OutboxStatus
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus
from api.webhooks import emitter
from api.webhooks.drainer import drain_webhook_batch
from api.webhooks.emitter import emit_event


class _Delivery:
    def __init__(self, *, result: bool = True, raises: bool = False) -> None:
        self._result = result
        self._raises = raises
        self.calls = 0

    async def deliver(self, payload: dict[str, Any]) -> bool:
        self.calls += 1
        if self._raises:
            raise ExternalServiceError("webhook", "deliver", "down")
        return self._result


async def _webhook_count(session: AsyncSession, status: OutboxStatus | None = None) -> int:
    stmt = select(func.count()).select_from(OutboxMessage).where(OutboxMessage.kind == "webhook")
    if status is not None:
        stmt = stmt.where(OutboxMessage.status == status)
    return int((await session.execute(stmt)).scalar_one())


async def test_emit_enqueues_when_url_set(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emitter, "get_settings", lambda: Settings(webhook_url="http://subscriber"))
    emit_event(
        session,
        event="request.created",
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.NEW,
    )
    await session.commit()
    assert await _webhook_count(session) == 1


async def test_emit_noop_when_disabled(session: AsyncSession) -> None:
    # По умолчанию webhook_url пуст → событие не эмитится.
    emit_event(
        session,
        event="request.created",
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.NEW,
    )
    await session.commit()
    assert await _webhook_count(session) == 0


async def _enqueue_webhook(session: AsyncSession) -> None:
    OutboxRepository(session).enqueue(
        "webhook", {"event": "request.created", "request_id": str(uuid.uuid4())}
    )
    await session.commit()


async def test_drain_delivers_and_marks_done(session: AsyncSession) -> None:
    await _enqueue_webhook(session)
    delivery = _Delivery(result=True)
    processed = await drain_webhook_batch(session, delivery, settings=Settings())
    assert processed == 1
    assert delivery.calls == 1
    assert await _webhook_count(session, OutboxStatus.DONE) == 1


async def test_drain_retries_on_unreachable(session: AsyncSession) -> None:
    await _enqueue_webhook(session)
    await drain_webhook_batch(session, _Delivery(raises=True), settings=Settings())
    # Недоступность → backoff-повтор (снова PENDING, attempts увеличен).
    assert await _webhook_count(session, OutboxStatus.PENDING) == 1


async def test_drain_retries_on_non_2xx(session: AsyncSession) -> None:
    await _enqueue_webhook(session)
    await drain_webhook_batch(session, _Delivery(result=False), settings=Settings())
    assert await _webhook_count(session, OutboxStatus.PENDING) == 1
