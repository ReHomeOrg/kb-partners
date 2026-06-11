"""Интеграционные тесты чтения и жизненного цикла заявок (M1.3).

Покрывают acceptance §13 «Сквозное» и инварианты CLAUDE.md:
- запрещённый переход FSM → 409;
- недоступный ресурс → 404 (НЕ 403) — двухконтурность/владение (правило 9);
- внутренние заметки `is_internal=true` невидимы заявителю/партнёру (правило 10).

Общие фикстуры (`session`, `make_client`) — из conftest.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.requests.enums import AccessLevel, ChannelIn, RequestStatus
from api.requests.models import RequestHistory, RequestMessage, ServiceRequest

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


async def _seed(
    session: AsyncSession,
    *,
    requester_id: str = "u-owner",
    partner_id: str | None = None,
    status: RequestStatus = RequestStatus.NEW,
    access_level: AccessLevel = AccessLevel.LOGGED,
    raw_input: str = "Реальный текст заявки",
    raw_input_masked: str = "Маскированный текст",
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-T-{uuid.uuid4().hex[:10]}",
        requester_id=requester_id,
        channel_in=ChannelIn.WEB_FORM,
        raw_input=raw_input,
        raw_input_masked=raw_input_masked,
        status=status,
        access_level=access_level,
        partner_id=partner_id,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


# --- GET /{id}: видимость и masking по scope --------------------------------


async def test_owner_requester_sees_detail_with_raw_input(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["raw_input"] == "Реальный текст заявки"  # владелец видит исходник
    assert RequestStatus.CLASSIFYING.value in body["allowed_transitions"]
    assert RequestStatus.CANCELLED.value in body["allowed_transitions"]


async def test_foreign_requester_gets_404_not_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="someone-else")
    stranger = _principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).get(f"{_BASE}/{req.id}")
    # Анти-enumeration: чужая заявка неотличима от несуществующей.
    assert resp.status_code == 404


async def test_unassigned_partner_gets_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    other_partner = _principal(PrincipalKind.PARTNER, partner_id="c-2")
    resp = await make_client(other_partner).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 404


async def test_assigned_partner_sees_masked_input_only(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    resp = await make_client(partner).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 200
    # Партнёр НЕ видит ПДн-исходник — только маску (FR-4.6).
    assert resp.json()["raw_input"] == "Маскированный текст"


async def test_operator_sees_any_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="u-x", access_level=AccessLevel.STAFF)
    operator = _principal(PrincipalKind.OPERATOR)
    resp = await make_client(operator).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 200
    assert resp.json()["raw_input"] == "Реальный текст заявки"


async def test_get_unknown_request_404(
    make_client: Callable[..., AsyncClient],
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    resp = await make_client(operator).get(f"{_BASE}/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_staff_access_level_hidden_from_requester(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    # Контур access_level: STAFF-заявка невидима заявителю даже как владельцу.
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id), access_level=AccessLevel.STAFF)
    resp = await make_client(owner).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 404


# --- GET (список): scope-фильтр + курсорная пагинация -----------------------


async def test_list_returns_only_own_requests(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    await _seed(session, requester_id=str(owner.user_id))
    await _seed(session, requester_id="other")
    resp = await make_client(owner).get(_BASE)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["requester_id"] == str(owner.user_id)


async def test_list_cursor_pagination(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    for _ in range(3):
        await _seed(session, requester_id=str(owner.user_id))
    client = make_client(owner)
    body1 = (await client.get(_BASE, params={"limit": 2})).json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None
    body2 = (await client.get(_BASE, params={"limit": 2, "cursor": body1["next_cursor"]})).json()
    assert len(body2["items"]) == 1  # три заявки владельца: 2 + 1
    assert body2["next_cursor"] is None
    ids1 = {i["id"] for i in body1["items"]}
    ids2 = {i["id"] for i in body2["items"]}
    assert ids1.isdisjoint(ids2)  # страницы не пересекаются


async def test_list_filter_by_status(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    await _seed(session, status=RequestStatus.NEW)
    await _seed(session, status=RequestStatus.MATCHING)
    resp = await make_client(operator).get(_BASE, params={"status": "MATCHING"})
    items = resp.json()["items"]
    assert items and all(i["status"] == "MATCHING" for i in items)


# --- POST /{id}/transition: FSM + RBAC + аудит ------------------------------


async def test_operator_transition_advances_status(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.NEW)
    resp = await make_client(operator).post(
        f"{_BASE}/{req.id}/transition", json={"target": "CLASSIFYING"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CLASSIFYING"
    hist = await session.scalar(
        select(RequestHistory).where(
            RequestHistory.request_id == req.id,
            RequestHistory.to_value == "CLASSIFYING",
        )
    )
    assert hist is not None and hist.from_value == "NEW"


async def test_forbidden_transition_returns_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.NEW)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/transition", json={"target": "DONE"})
    assert resp.status_code == 409


async def test_requester_cannot_transition_own_request_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/transition", json={"target": "CLASSIFYING"}
    )
    # Видит свою заявку (404 исключён), но управлять FSM не вправе → 403.
    assert resp.status_code == 403


async def test_transition_foreign_request_404_for_requester(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).post(
        f"{_BASE}/{req.id}/transition", json={"target": "CLASSIFYING"}
    )
    assert resp.status_code == 404  # 404 приоритетнее 403


async def test_transition_sets_lifecycle_timestamp(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.ASSIGNED)
    await make_client(operator).post(f"{_BASE}/{req.id}/transition", json={"target": "DISPATCHED"})
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.dispatched_at is not None


# --- POST /{id}/cancel ------------------------------------------------------


async def test_requester_cancels_own_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/cancel", json={"reason": "передумал"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None
    assert refreshed.custom_fields["cancellation"]["reason"] == "передумал"


async def test_partner_cannot_cancel_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    resp = await make_client(partner).post(f"{_BASE}/{req.id}/cancel", json={"reason": "не хочу"})
    assert resp.status_code == 403


async def test_cancel_terminal_request_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.CANCELLED)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/cancel", json={"reason": "повтор"})
    assert resp.status_code == 409


# --- Сообщения и КРИТИЧНЫЙ инвариант is_internal ----------------------------


async def test_operator_can_post_internal_note(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session)
    resp = await make_client(operator).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "внутренняя пометка", "is_internal": True},
    )
    assert resp.status_code == 201
    assert resp.json()["is_internal"] is True


async def test_requester_message_is_external(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages", json={"text": "вопрос по заявке"}
    )
    assert resp.status_code == 201
    assert resp.json()["is_internal"] is False
    assert resp.json()["author_type"] == "REQUESTER"


async def test_requester_cannot_post_internal_note_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "секрет", "is_internal": True},
    )
    assert resp.status_code == 403


async def test_partner_cannot_post_internal_note_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "секрет", "is_internal": True},
    )
    assert resp.status_code == 403


async def test_internal_notes_hidden_from_requester(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    # КРИТИЧНЫЙ security-тест (правило 10): заметка оператора не утекает заявителю.
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    session.add(
        RequestMessage(
            request_id=req.id,
            author_type="OPERATOR",
            is_internal=True,
            text="служебная заметка — НЕ показывать",
        )
    )
    session.add(
        RequestMessage(
            request_id=req.id,
            author_type="REQUESTER",
            is_internal=False,
            text="видимое сообщение",
        )
    )
    await session.commit()

    resp = await make_client(owner).get(f"{_BASE}/{req.id}/messages")
    assert resp.status_code == 200
    texts = [m["text"] for m in resp.json()]
    assert "видимое сообщение" in texts
    assert all(not m["is_internal"] for m in resp.json())
    assert "служебная заметка — НЕ показывать" not in texts


async def test_internal_notes_hidden_from_partner(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    session.add(
        RequestMessage(request_id=req.id, author_type="OPERATOR", is_internal=True, text="секрет")
    )
    await session.commit()
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    resp = await make_client(partner).get(f"{_BASE}/{req.id}/messages")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_operator_sees_internal_notes(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session)
    session.add(
        RequestMessage(request_id=req.id, author_type="OPERATOR", is_internal=True, text="секрет")
    )
    await session.commit()
    resp = await make_client(operator).get(f"{_BASE}/{req.id}/messages")
    assert resp.status_code == 200
    assert any(m["is_internal"] for m in resp.json())


async def test_post_message_to_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/messages", json={"text": "привет"})
    assert resp.status_code == 404


async def test_list_messages_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).get(f"{_BASE}/{req.id}/messages")
    assert resp.status_code == 404


async def test_cancel_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/cancel", json={"reason": "чужая"})
    assert resp.status_code == 404
