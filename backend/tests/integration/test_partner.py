"""Интеграционные тесты ответа партнёра (E10 портал LIGHT, FR-10.2)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import RequestMessage, ServiceRequest

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


async def _seed(
    session: AsyncSession,
    *,
    partner_id: str = "c-1",
    status: RequestStatus = RequestStatus.DISPATCHED,
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-P-{uuid.uuid4().hex[:8]}",
        requester_id="u-owner",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="уборка",
        raw_input_masked="уборка",
        status=status,
        access_level=AccessLevel.LOGGED,
        category=Category.CLEANING,
        partner_id=partner_id,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


async def test_partner_accepts_and_starts_perform_sla(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1")
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "accepted", "message": "берём"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.ACCEPTED.value
    assert body["sla"]["perform_deadline"]  # SLA выполнения стартовал
    msg = await session.scalar(select(RequestMessage).where(RequestMessage.request_id == req.id))
    assert msg is not None and msg.author_type.value == "PARTNER" and msg.text == "берём"


async def test_partner_rejects_to_matching(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1")
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "rejected"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.MATCHING.value


async def test_partner_progresses_in_progress(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1", status=RequestStatus.ACCEPTED)
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "in_progress"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.IN_PROGRESS.value


async def test_non_partner_forbidden_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session)
    resp = await make_client(operator).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "accepted"}
    )
    assert resp.status_code == 403


async def test_other_partner_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, partner_id="c-1")
    other = _principal(PrincipalKind.PARTNER, partner_id="c-2")
    resp = await make_client(other).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "accepted"}
    )
    assert resp.status_code == 404


async def test_partner_unknown_status_422(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1")
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "weird"}
    )
    assert resp.status_code == 422


async def test_partner_illegal_transition_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    # done из DISPATCHED — нелегально (нужно ACCEPTED→IN_PROGRESS→DONE).
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1", status=RequestStatus.DISPATCHED)
    resp = await make_client(partner).post(
        f"{_BASE}/{req.id}/partner-response", json={"status": "done"}
    )
    assert resp.status_code == 409
