"""Интеграционные тесты requester-context (E9, §11.1, FR-9.1)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.clients.rehome.models import RequesterContext, SettlementRef
from api.main import app
from api.requests.context import ContextService
from api.requests.dependencies import get_context_service
from api.requests.enums import AccessLevel, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


class _FakeRehome:
    def __init__(self, ctx: RequesterContext | None) -> None:
        self._ctx = ctx

    async def trigger_settlement(
        self, *, request_id: str, service_order_id: str | None, idempotency_key: str
    ) -> SettlementRef | None:
        return None

    async def get_requester_context(
        self, *, requester_id: str, premises_id: str | None, booking_id: str | None
    ) -> RequesterContext | None:
        return self._ctx


def _use_context(session: AsyncSession, ctx: RequesterContext | None) -> None:
    async def _dep() -> AsyncIterator[ContextService]:
        yield ContextService(session, _FakeRehome(ctx))

    app.dependency_overrides[get_context_service] = _dep


async def _seed(session: AsyncSession, *, requester_id: str = "u-owner") -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-CTX-{uuid.uuid4().hex[:8]}",
        requester_id=requester_id,
        channel_in=ChannelIn.WEB_FORM,
        raw_input="уборка",
        raw_input_masked="уборка",
        status=RequestStatus.NEW,
        access_level=AccessLevel.LOGGED,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


async def test_operator_gets_context(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session)
    _use_context(
        session,
        RequesterContext(user_display_name="Иван", premises_address="Москва, ул. Ленина 1"),
    )
    resp = await make_client(operator).get(f"{_BASE}/{req.id}/requester-context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_display_name"] == "Иван"
    assert body["premises_address"] == "Москва, ул. Ленина 1"


async def test_context_empty_when_circuit_unavailable(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session)
    _use_context(session, None)  # контур недоступен/инертен
    resp = await make_client(operator).get(f"{_BASE}/{req.id}/requester-context")
    assert resp.status_code == 200
    assert resp.json()["user_display_name"] is None


async def test_requester_cannot_get_context_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _use_context(session, RequesterContext(user_display_name="Иван"))
    resp = await make_client(owner).get(f"{_BASE}/{req.id}/requester-context")
    assert resp.status_code == 403


async def test_agent_on_behalf_gets_context(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    user = uuid.uuid4()
    agent = _principal(PrincipalKind.AGENT, on_behalf_of=user)
    req = await _seed(session, requester_id=str(user))
    _use_context(session, RequesterContext(user_display_name="Пётр"))
    resp = await make_client(agent).get(f"{_BASE}/{req.id}/requester-context")
    assert resp.status_code == 200
    assert resp.json()["user_display_name"] == "Пётр"


async def test_context_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    _use_context(session, RequesterContext())
    resp = await make_client(stranger).get(f"{_BASE}/{req.id}/requester-context")
    assert resp.status_code == 404
