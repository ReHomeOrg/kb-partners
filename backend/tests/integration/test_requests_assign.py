"""Интеграционные тесты подбора/назначения (E3, FR-3.1–3.4, acceptance E3).

`get_assignment_service` переопределяется на сервис с ФЕЙКОВЫМ platform-клиентом
(без сети) поверх тест-сессии. Matcher — настоящий.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.clients.platform.models import CollaboratorCandidate, PartnerContact, ServiceOrderRef
from api.main import app
from api.matching.engine import Matcher
from api.requests.dependencies import get_assignment_service
from api.requests.enums import AccessLevel, Category, ChannelIn, HistoryAction, RequestStatus
from api.requests.models import RequestHistory, ServiceRequest
from api.requests.service import AssignmentService

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


class _FakePlatformClient:
    """Фейковый реестр: кандидаты по категории + заданный результат ServiceOrder."""

    def __init__(
        self, candidates: list[CollaboratorCandidate], order_ref: ServiceOrderRef | None = None
    ) -> None:
        self._candidates = candidates
        self._order_ref = order_ref

    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        return [c for c in self._candidates if c.category == category]

    async def create_service_order(
        self, *, request_id: str, partner_id: str, category: str, idempotency_key: str
    ) -> ServiceOrderRef | None:
        return self._order_ref

    async def get_partner_contact(self, *, partner_id: str) -> PartnerContact | None:
        return None


def _candidate(
    cid: str, *, rating: float, channels: tuple[str, ...] = ("API",)
) -> CollaboratorCandidate:
    return CollaboratorCandidate(
        id=cid,
        name=cid,
        category="CLEANING",
        is_active=True,
        available=True,
        rating=rating,
        service_areas=(),
        channels=channels,
    )


def _use_candidates(
    session: AsyncSession,
    candidates: list[CollaboratorCandidate],
    *,
    require_order: bool = False,
    order_ref: ServiceOrderRef | None = None,
) -> None:
    async def _dep() -> AsyncIterator[AssignmentService]:
        yield AssignmentService(
            session,
            _FakePlatformClient(candidates, order_ref),
            Matcher(),
            require_service_order=require_order,
        )

    app.dependency_overrides[get_assignment_service] = _dep


async def test_auto_assign_picks_best_and_sets_fallback(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session)
    _use_candidates(session, [_candidate("c-1", rating=4.0), _candidate("c-2", rating=4.9)])
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.ASSIGNED.value
    assert body["partner_id"] == "c-2"
    assert body["delivery_channel"] == "API"
    assert body["fallback_chain"] == ["c-1"]
    assert body["match_trace"]["method"] == "auto"
    hist = await session.scalar(
        select(RequestHistory).where(
            RequestHistory.request_id == req.id, RequestHistory.action == HistoryAction.ASSIGNED
        )
    )
    assert hist is not None and hist.to_value == "c-2"


async def test_manual_assign_sets_partner(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session)
    _use_candidates(session, [])  # авто-подбор не используется
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={"partner_id": "c-9"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["partner_id"] == "c-9"
    assert body["status"] == RequestStatus.ASSIGNED.value
    assert body["match_trace"]["method"] == "manual"


async def test_auto_assign_no_candidates_422(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session)
    _use_candidates(session, [])
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 422


async def test_assign_requester_forbidden_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed_classified(session, requester_id=str(owner.user_id))
    _use_candidates(session, [_candidate("c-1", rating=4.0)])
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 403


async def test_assign_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_classified(session, requester_id="other")
    stranger = _principal(PrincipalKind.REQUESTER)
    _use_candidates(session, [_candidate("c-1", rating=4.0)])
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 404


async def test_assign_wrong_status_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session, status=RequestStatus.NEW)
    _use_candidates(session, [_candidate("c-1", rating=4.0)])
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 409


async def test_auto_assign_unclassified_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    # MATCHING-статус допустим, но без категории авто-подбор невозможен.
    req = await _seed_classified(session, status=RequestStatus.MATCHING, category=None)
    _use_candidates(session, [_candidate("c-1", rating=4.0)])
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 409


async def test_reassign_from_failed_dispatch(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session, status=RequestStatus.FAILED_DISPATCH)
    _use_candidates(session, [_candidate("c-1", rating=4.0)])
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.ASSIGNED.value


async def test_match_trace_hidden_from_requester(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    owner_id = str(uuid.uuid4())
    req = await _seed_classified(session, requester_id=owner_id)
    _use_candidates(session, [_candidate("c-1", rating=4.0), _candidate("c-2", rating=4.5)])
    await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    # Владелец видит назначенного партнёра, но не объяснимость/конкурентов.
    owner = Principal(user_id=uuid.UUID(owner_id), kind=PrincipalKind.REQUESTER)
    resp = await make_client(owner).get(f"{_BASE}/{req.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["partner_id"] == "c-2"
    assert body["match_trace"] is None
    assert body["fallback_chain"] is None


async def test_auto_assign_creates_service_order(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session)
    _use_candidates(
        session,
        [_candidate("c-1", rating=4.0)],
        require_order=True,
        order_ref=ServiceOrderRef(id="so-1", status="DRAFT"),
    )
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 200
    assert resp.json()["service_order_id"] == "so-1"


async def test_assign_502_when_service_order_unavailable(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_classified(session)
    _use_candidates(session, [_candidate("c-1", rating=4.0)], require_order=True, order_ref=None)
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/assign", json={})
    assert resp.status_code == 502
    # Заказ не создан → ничего не закоммичено: заявка осталась в исходном статусе.
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None
    assert refreshed.status is RequestStatus.CLASSIFIED


async def _seed_classified(
    session: AsyncSession,
    *,
    requester_id: str = "u-owner",
    status: RequestStatus = RequestStatus.CLASSIFIED,
    category: Category | None = Category.CLEANING,
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-A-{uuid.uuid4().hex[:10]}",
        requester_id=requester_id,
        channel_in=ChannelIn.WEB_FORM,
        raw_input="нужна уборка",
        raw_input_masked="нужна уборка",
        status=status,
        access_level=AccessLevel.LOGGED,
        category=category,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request
