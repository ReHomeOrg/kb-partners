"""Интеграционные тесты приёма заявок (эпик E1, FR-1.1–FR-1.6, acceptance E1).

Гоняются против реальной БД (DSN из Settings, dev-порт 5434). Изоляция —
внешняя транзакция на соединении + `join_transaction_mode="create_savepoint"`:
коммиты сервиса уходят в SAVEPOINT, внешний rollback в teardown откатывает всё.
(Последовательность номеров не транзакционна — номера не сбрасываются между
тестами, поэтому проверяется формат `RQ-`, а не конкретное значение.)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.requests.enums import ChannelIn, HistoryAction, RequestStatus
from api.requests.models import RequestHistory, ServiceRequest

# `session` и `make_client` — общие фикстуры из tests/integration/conftest.py.


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


_REQUESTS = "/api/v1/partners/requests"


# --- POST /requests -------------------------------------------------------


async def test_create_request_as_requester_201(make_client: Callable[..., AsyncClient]) -> None:
    principal = _principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    resp = await client.post(_REQUESTS, json={"raw_input": "Нужна уборка квартиры"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["number"].startswith("RQ-")
    assert body["channel_in"] == ChannelIn.WEB_FORM.value
    assert body["status"] == RequestStatus.NEW.value
    assert body["category"] is None
    # Заявитель создаёт только от своего имени (id из токена).
    assert body["requester_id"] == str(principal.user_id)
    # ПДн-поле raw_input наружу не отдаётся (FR-1.6/NFR-5).
    assert "raw_input" not in body


async def test_requester_cannot_spoof_requester_id(
    make_client: Callable[..., AsyncClient],
) -> None:
    principal = _principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    resp = await client.post(
        _REQUESTS, json={"raw_input": "уборка", "requester_id": "victim-user-id"}
    )
    assert resp.status_code == 201
    assert resp.json()["requester_id"] == str(principal.user_id)


async def test_create_request_requires_auth(make_client: Callable[..., AsyncClient]) -> None:
    # Без принципала — реальная зависимость: auth не сконфигурирован → 401.
    client = make_client(None)
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка"})
    assert resp.status_code == 401


async def test_create_request_validation_error(
    make_client: Callable[..., AsyncClient],
) -> None:
    client = make_client(_principal(PrincipalKind.REQUESTER))
    resp = await client.post(_REQUESTS, json={"raw_input": ""})
    assert resp.status_code == 422


async def test_service_requester_id_required(make_client: Callable[..., AsyncClient]) -> None:
    client = make_client(_principal(PrincipalKind.SERVICE))
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка"})
    assert resp.status_code == 400


async def test_idempotent_replay_returns_same_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    client = make_client(_principal(PrincipalKind.REQUESTER))
    headers = {"Idempotency-Key": "form-key-1"}
    first = await client.post(_REQUESTS, json={"raw_input": "уборка"}, headers=headers)
    second = await client.post(_REQUESTS, json={"raw_input": "уборка"}, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200  # повтор — не дубль
    assert first.json()["id"] == second.json()["id"]
    rows = list(
        await session.scalars(
            select(ServiceRequest).where(ServiceRequest.idempotency_key == "form-key-1")
        )
    )
    assert len(rows) == 1


async def test_raw_input_is_masked_before_storage(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    client = make_client(_principal(PrincipalKind.REQUESTER))
    raw = "Звоните мне на +7 916 123-45-67 или ivan@example.com"
    resp = await client.post(_REQUESTS, json={"raw_input": raw})
    request_id = uuid.UUID(resp.json()["id"])
    row = await session.get(ServiceRequest, request_id)
    assert row is not None
    assert row.raw_input == raw  # исходник сохранён (ретенция NFR-12)
    assert "***" in row.raw_input_masked
    assert "ivan@example.com" not in row.raw_input_masked
    assert "916" not in row.raw_input_masked


async def test_create_writes_history_record(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    principal = _principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка"})
    request_id = uuid.UUID(resp.json()["id"])
    history = list(
        await session.scalars(select(RequestHistory).where(RequestHistory.request_id == request_id))
    )
    assert len(history) == 1
    assert history[0].action is HistoryAction.CREATED
    assert history[0].to_value == RequestStatus.NEW.value
    assert history[0].actor_id == principal.user_id


async def test_operator_can_set_requester_id(
    make_client: Callable[..., AsyncClient],
) -> None:
    client = make_client(_principal(PrincipalKind.OPERATOR))
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка", "requester_id": "u-managed"})
    assert resp.status_code == 201
    assert resp.json()["requester_id"] == "u-managed"


async def test_operator_without_requester_id_uses_own(
    make_client: Callable[..., AsyncClient],
) -> None:
    principal = _principal(PrincipalKind.OPERATOR)
    client = make_client(principal)
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка"})
    assert resp.status_code == 201
    assert resp.json()["requester_id"] == str(principal.user_id)


async def test_agent_on_behalf_of_used_as_requester(
    make_client: Callable[..., AsyncClient],
) -> None:
    user = uuid.uuid4()
    principal = _principal(PrincipalKind.AGENT, on_behalf_of=user)
    client = make_client(principal)
    resp = await client.post(_REQUESTS, json={"raw_input": "уборка"})
    assert resp.status_code == 201
    assert resp.json()["requester_id"] == str(user)


# --- POST /requests/from-chat (SERVICE-only) ------------------------------


async def test_from_chat_requires_service(make_client: Callable[..., AsyncClient]) -> None:
    client = make_client(_principal(PrincipalKind.REQUESTER))
    resp = await client.post(
        f"{_REQUESTS}/from-chat",
        json={"chat_session_id": "s1", "requester_id": "u1", "raw_input": "переезд"},
    )
    assert resp.status_code == 403


async def test_from_chat_creates_ai_chat_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    agent_user = uuid.uuid4()
    principal = _principal(PrincipalKind.SERVICE, on_behalf_of=agent_user)
    client = make_client(principal)
    resp = await client.post(
        f"{_REQUESTS}/from-chat",
        json={
            "chat_session_id": "sess-42",
            "requester_id": "u-77",
            "raw_input": "Нужен переезд",
            "transcript": [{"role": "user", "text": "переезд"}],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["channel_in"] == ChannelIn.AI_CHAT.value
    assert body["requester_id"] == "u-77"
    row = await session.get(ServiceRequest, uuid.UUID(body["id"]))
    assert row is not None
    assert row.source_ref == {
        "chat_session_id": "sess-42",
        "transcript": [{"role": "user", "text": "переезд"}],
    }
    # Аудит атрибутирован пользователю (on-behalf-of), а не сервис-принципалу.
    hist = await session.scalar(select(RequestHistory).where(RequestHistory.request_id == row.id))
    assert hist is not None and hist.actor_id == agent_user


async def test_from_chat_idempotent_by_session(
    make_client: Callable[..., AsyncClient],
) -> None:
    client = make_client(_principal(PrincipalKind.SERVICE))
    payload = {"chat_session_id": "dup", "requester_id": "u1", "raw_input": "переезд"}
    first = await client.post(f"{_REQUESTS}/from-chat", json=payload)
    second = await client.post(f"{_REQUESTS}/from-chat", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


# --- POST /requests/from-ticket (SERVICE-only) ----------------------------


async def test_from_ticket_requires_service(make_client: Callable[..., AsyncClient]) -> None:
    client = make_client(_principal(PrincipalKind.OPERATOR))
    resp = await client.post(
        f"{_REQUESTS}/from-ticket",
        json={"ticket_id": "t1", "requester_id": "u1", "raw_input": "ремонт"},
    )
    assert resp.status_code == 403


async def test_from_ticket_creates_support_ticket_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    client = make_client(_principal(PrincipalKind.SERVICE))
    resp = await client.post(
        f"{_REQUESTS}/from-ticket",
        json={"ticket_id": "TCK-9", "requester_id": "u-9", "raw_input": "Нужен ремонт крана"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["channel_in"] == ChannelIn.SUPPORT_TICKET.value
    row = await session.get(ServiceRequest, uuid.UUID(body["id"]))
    assert row is not None
    assert row.source_ref == {"ticket_id": "TCK-9"}
