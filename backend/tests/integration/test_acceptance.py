"""Интеграционные тесты приёмки/спора (E7, FR-7.1/7.2, acceptance E7).

`get_acceptance_service` переопределяется на сервис с фейковым kb-support-клиентом.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.clients.rehome.models import SettlementRef
from api.clients.support.models import ClaimRef
from api.main import app
from api.requests.acceptance import AcceptanceService
from api.requests.dependencies import get_acceptance_service
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


class _FakeSupport:
    def __init__(self, claim_ref: ClaimRef | None) -> None:
        self._claim_ref = claim_ref

    async def create_compensation_claim(
        self, *, request_id: str, requester_id: str, reason: str, idempotency_key: str
    ) -> ClaimRef | None:
        return self._claim_ref


class _FakeRehome:
    def __init__(self, ref: SettlementRef | None) -> None:
        self._ref = ref

    async def trigger_settlement(
        self, *, request_id: str, service_order_id: str | None, idempotency_key: str
    ) -> SettlementRef | None:
        return self._ref


def _use_acceptance(
    session: AsyncSession,
    *,
    claim_ref: ClaimRef | None = None,
    enable: bool = False,
    settlement_ref: SettlementRef | None = None,
    enable_settlement: bool = False,
) -> None:
    async def _dep() -> AsyncIterator[AcceptanceService]:
        yield AcceptanceService(
            session,
            _FakeSupport(claim_ref),
            _FakeRehome(settlement_ref),
            enable_claims=enable,
            enable_settlement=enable_settlement,
        )

    app.dependency_overrides[get_acceptance_service] = _dep


async def _seed(
    session: AsyncSession,
    *,
    requester_id: str = "u-owner",
    partner_id: str | None = "c-1",
    status: RequestStatus = RequestStatus.DONE,
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-E7-{uuid.uuid4().hex[:8]}",
        requester_id=requester_id,
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


async def test_owner_accepts_done_request(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _use_acceptance(session)
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/accept")
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.ACCEPTED_BY_USER.value


async def test_accept_wrong_status_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.NEW)
    _use_acceptance(session)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/accept")
    assert resp.status_code == 409


async def test_partner_cannot_accept_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1")
    _use_acceptance(session)
    resp = await make_client(partner).post(f"{_BASE}/{req.id}/accept")
    assert resp.status_code == 403


async def test_dispute_creates_compensation_claim(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _use_acceptance(session, claim_ref=ClaimRef(id="cl-1", status="OPEN"), enable=True)
    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/dispute", json={"reason": "плохо убрали"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.DISPUTE.value
    assert body["claim_ref"] == "cl-1"
    assert body["dispute_id"] == "cl-1"


async def test_dispute_from_accepted_by_user(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.ACCEPTED_BY_USER)
    _use_acceptance(session)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispute", json={"reason": "спор"})
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.DISPUTE.value


async def test_dispute_inert_when_claims_disabled(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _use_acceptance(session, enable=False)  # контур претензий не сконфигурирован
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/dispute", json={"reason": "спор"})
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.DISPUTE.value
    assert resp.json()["claim_ref"] is None  # спор открыт, претензия не создавалась


async def test_dispute_partner_forbidden_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    partner = _principal(PrincipalKind.PARTNER, partner_id="c-1")
    req = await _seed(session, partner_id="c-1")
    _use_acceptance(session)
    resp = await make_client(partner).post(f"{_BASE}/{req.id}/dispute", json={"reason": "x"})
    assert resp.status_code == 403


async def test_accept_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    _use_acceptance(session)
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/accept")
    assert resp.status_code == 404


async def test_accept_triggers_settlement_and_stores_refs(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _use_acceptance(
        session,
        settlement_ref=SettlementRef(status="PENDING", amount_ref="a-1", escrow_ref="e-1"),
        enable_settlement=True,
    )
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/accept")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.ACCEPTED_BY_USER.value
    assert body["amount_ref"] == "a-1"
    assert body["escrow_ref"] == "e-1"


async def test_settlement_confirm_to_paid(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    service = _principal(PrincipalKind.SERVICE)
    req = await _seed(session, status=RequestStatus.ACCEPTED_BY_USER)
    _use_acceptance(session)
    resp = await make_client(service).post(
        f"{_BASE}/{req.id}/settlement", json={"amount_ref": "a-2"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.PAID.value
    assert body["amount_ref"] == "a-2"


async def test_settlement_wrong_status_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    service = _principal(PrincipalKind.SERVICE)
    req = await _seed(session, status=RequestStatus.DONE)
    _use_acceptance(session)
    resp = await make_client(service).post(f"{_BASE}/{req.id}/settlement", json={})
    assert resp.status_code == 409


async def test_settlement_requires_service_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed(session, status=RequestStatus.ACCEPTED_BY_USER)
    _use_acceptance(session)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/settlement", json={})
    assert resp.status_code == 403
