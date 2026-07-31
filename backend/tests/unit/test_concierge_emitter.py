"""Юнит-тесты эмиссии колбэка статуса в Консьерж (E9, U3, issue #7): гейтинг + карта."""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent.callback import (
    CONCIERGE_CALLBACK_KIND,
    emit_concierge_status_update,
    status_text,
)
from api.config import Settings
from api.requests.enums import RequestStatus

_ON = Settings(concierge_api_base_url="http://concierge")
_OFF = Settings()


class _FakeSession:
    """Записывает `add()` — эмиттер кладёт OutboxMessage через OutboxRepository."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def _patch(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr("api.agent.callback.get_settings", lambda: settings)


def _emit(
    session: _FakeSession,
    *,
    status: RequestStatus,
    source_ref: dict[str, Any] | None,
    number: str = "RQ-1",
    request_id: uuid.UUID | None = None,
) -> None:
    """Вызвать эмиттер с фейковой сессией (каст — фейк реализует только `add`)."""
    emit_concierge_status_update(
        cast(AsyncSession, session),
        request_id=request_id or uuid.uuid4(),
        number=number,
        status=status,
        source_ref=source_ref,
    )


# --- Карта значимых статусов (status_text) ---


def test_status_text_significant_includes_number() -> None:
    for status in (
        RequestStatus.ASSIGNED,
        RequestStatus.DISPATCHED,
        RequestStatus.DONE,
        RequestStatus.CANCELLED,
        RequestStatus.PAID,
        RequestStatus.DISPUTE,
    ):
        text = status_text(status, "RQ-42")
        assert text is not None and "RQ-42" in text, status


def test_status_text_intermediate_is_none() -> None:
    # Технические рёбра FSM не уведомляют (реш. Архитектора «только значимые»).
    for status in (
        RequestStatus.NEW,
        RequestStatus.CLASSIFYING,
        RequestStatus.CLASSIFIED,
        RequestStatus.NEEDS_REVIEW,
        RequestStatus.MATCHING,
    ):
        assert status_text(status, "RQ-1") is None, status


# --- Гейтинг эмиссии ---


def test_emit_off_when_base_url_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _OFF)
    session = _FakeSession()
    _emit(session, status=RequestStatus.ASSIGNED, source_ref={"chat_session_id": "sess-1"})
    assert session.added == []


def test_emit_skips_non_chat_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _ON)
    session = _FakeSession()
    _emit(session, status=RequestStatus.ASSIGNED, source_ref=None)
    _emit(session, status=RequestStatus.ASSIGNED, source_ref={"ticket_id": "T-1"})
    assert session.added == []


def test_emit_skips_intermediate_status(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _ON)
    session = _FakeSession()
    _emit(session, status=RequestStatus.CLASSIFYING, source_ref={"chat_session_id": "sess-1"})
    assert session.added == []


def test_emit_enqueues_significant_from_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _ON)
    session = _FakeSession()
    request_id = uuid.uuid4()
    _emit(
        session,
        status=RequestStatus.DONE,
        source_ref={"chat_session_id": "sess-9"},
        number="RQ-7",
        request_id=request_id,
    )
    assert len(session.added) == 1
    message = session.added[0]
    assert message.kind == CONCIERGE_CALLBACK_KIND
    assert message.payload["session_id"] == "sess-9"
    assert message.payload["ref"] == "RQ-7"
    assert message.payload["status"] == "DONE"
    assert "RQ-7" in message.payload["text"]
    assert message.payload["request_id"] == str(request_id)


def test_emit_payload_has_no_pii(monkeypatch: pytest.MonkeyPatch) -> None:
    # ФЗ-152 (G3): наружу только служебные поля; raw_input/ПДн из source_ref не утекают.
    _patch(monkeypatch, _ON)
    session = _FakeSession()
    _emit(
        session,
        status=RequestStatus.DONE,
        source_ref={"chat_session_id": "sess-9", "raw_input": "ПДн-адрес заявителя"},
        number="RQ-7",
    )
    payload = session.added[0].payload
    assert set(payload) == {"session_id", "text", "ref", "status", "request_id"}
    assert "raw_input" not in payload
    assert "ПДн" not in payload["text"]
