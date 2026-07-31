"""Интеграционные тесты колбэка статуса в Консьерж (E9, U3, #7): эмиссия в outbox + дрейн."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent import callback
from api.agent.callback import CONCIERGE_CALLBACK_KIND, emit_concierge_status_update
from api.agent.drainer import drain_concierge_callback_batch
from api.clients.errors import ExternalServiceError
from api.config import Settings
from api.outbox.models import OutboxMessage, OutboxStatus
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus

_ON = Settings(concierge_api_base_url="http://concierge")


class _Concierge:
    def __init__(self, *, result: bool = True, raises: bool = False) -> None:
        self._result = result
        self._raises = raises
        self.calls = 0

    async def deliver_status_update(self, payload: dict[str, Any]) -> bool:
        self.calls += 1
        if self._raises:
            raise ExternalServiceError("concierge", "deliver", "down")
        return self._result


async def _count(session: AsyncSession, status: OutboxStatus | None = None) -> int:
    stmt = (
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.kind == CONCIERGE_CALLBACK_KIND)
    )
    if status is not None:
        stmt = stmt.where(OutboxMessage.status == status)
    return int((await session.execute(stmt)).scalar_one())


def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(callback, "get_settings", lambda: _ON)


# --- Эмиссия ---


async def test_emit_enqueues_for_chat_significant(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(monkeypatch)
    emit_concierge_status_update(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.DONE,
        source_ref={"chat_session_id": "sess-1"},
    )
    await session.commit()
    assert await _count(session) == 1


async def test_emit_noop_when_disabled(session: AsyncSession) -> None:
    # По умолчанию concierge_api_base_url пуст → колбэк не эмитится.
    emit_concierge_status_update(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.DONE,
        source_ref={"chat_session_id": "sess-1"},
    )
    await session.commit()
    assert await _count(session) == 0


async def test_emit_noop_when_not_from_chat(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(monkeypatch)
    emit_concierge_status_update(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.DONE,
        source_ref=None,
    )
    await session.commit()
    assert await _count(session) == 0


async def test_emit_noop_for_intermediate_status(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _on(monkeypatch)
    emit_concierge_status_update(
        session,
        request_id=uuid.uuid4(),
        number="RQ-1",
        status=RequestStatus.CLASSIFYING,
        source_ref={"chat_session_id": "sess-1"},
    )
    await session.commit()
    assert await _count(session) == 0


# --- Дрейн ---


async def _enqueue(session: AsyncSession) -> None:
    OutboxRepository(session).enqueue(
        CONCIERGE_CALLBACK_KIND,
        {
            "session_id": "sess-1",
            "text": "Заявка RQ-1 завершена.",
            "ref": "RQ-1",
            "status": "DONE",
            "request_id": str(uuid.uuid4()),
        },
    )
    await session.commit()


async def test_drain_delivers_and_marks_done(session: AsyncSession) -> None:
    await _enqueue(session)
    client = _Concierge(result=True)
    processed = await drain_concierge_callback_batch(session, client, settings=Settings())
    assert processed == 1
    assert client.calls == 1
    assert await _count(session, OutboxStatus.DONE) == 1


async def test_drain_retries_on_unreachable(session: AsyncSession) -> None:
    await _enqueue(session)
    await drain_concierge_callback_batch(session, _Concierge(raises=True), settings=Settings())
    assert await _count(session, OutboxStatus.PENDING) == 1


async def test_drain_retries_on_non_2xx(session: AsyncSession) -> None:
    await _enqueue(session)
    await drain_concierge_callback_batch(session, _Concierge(result=False), settings=Settings())
    assert await _count(session, OutboxStatus.PENDING) == 1
