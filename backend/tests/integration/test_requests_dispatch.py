"""Интеграционные тесты диспетчеризации (E4, FR-4.1–4.6, acceptance E4).

`get_dispatch_service` переопределяется на сервис с фейковым резолвером каналов
(исход доставки задаётся по collaborator_id). Каналы партнёров — реальные строки
`partner_channel_configs` в тест-сессии.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.channels.dependencies import get_dispatch_service
from api.channels.dispatch import DispatchService
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.models import DispatchAttempt, PartnerChannelConfig
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.channels.resolver import ChannelResolver
from api.config import Settings
from api.main import app
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.sla.engine import SlaPolicy

_BASE = "/api/v1/partners/requests"


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


class _MapChannel:
    """Канал, чей исход зависит от collaborator_id (для проверки fallback)."""

    channel_type = ChannelType.MOCK

    def __init__(self, outcomes: dict[str, DeliveryOutcome]) -> None:
        self._outcomes = outcomes

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        outcome = self._outcomes.get(config.collaborator_id, DeliveryOutcome.FAILED)
        return DeliveryResult(outcome=outcome, provider_response={"fake": True})

    async def parse_inbound(
        self, payload: dict[str, object], config: ChannelConfig
    ) -> StatusUpdate | None:
        return None

    async def healthcheck(self, config: ChannelConfig) -> Health:
        return Health(status=HealthStatus.HEALTHY)


class _MapResolver:
    def __init__(self, outcomes: dict[str, DeliveryOutcome]) -> None:
        self._outcomes = outcomes

    def resolve(
        self, config: PartnerChannelConfig
    ) -> contextlib.AbstractAsyncContextManager[_MapChannel]:
        @contextlib.asynccontextmanager
        async def _ctx() -> AsyncIterator[_MapChannel]:
            yield _MapChannel(self._outcomes)

        return _ctx()


def _use_resolver(session: AsyncSession, outcomes: dict[str, DeliveryOutcome]) -> None:
    def _dep() -> DispatchService:
        resolver: ChannelResolver = _MapResolver(outcomes)
        return DispatchService(session, resolver, SlaPolicy.from_settings(Settings()))

    app.dependency_overrides[get_dispatch_service] = _dep


async def _seed_assigned(
    session: AsyncSession,
    *,
    partner_id: str | None = "c-1",
    fallback: list[str] | None = None,
    status: RequestStatus = RequestStatus.ASSIGNED,
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-D-{uuid.uuid4().hex[:10]}",
        requester_id="u-owner",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="нужна уборка",
        raw_input_masked="нужна уборка",
        status=status,
        access_level=AccessLevel.LOGGED,
        category=Category.CLEANING,
        partner_id=partner_id,
        fallback_chain=fallback,
        classification={"params": {"area_sqm": 50}},
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


async def _seed_channel(session: AsyncSession, collaborator_id: str) -> None:
    session.add(
        PartnerChannelConfig(
            collaborator_id=collaborator_id,
            channel_type=ChannelType.MOCK,
            priority=10,
            config={},
            is_active=True,
        )
    )
    await session.commit()


async def _attempt_count(session: AsyncSession, request_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(DispatchAttempt)
        .where(DispatchAttempt.request_id == request_id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def test_dispatch_success_records_attempt(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_assigned(session, partner_id="c-1")
    await _seed_channel(session, "c-1")
    _use_resolver(session, {"c-1": DeliveryOutcome.SENT})
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.DISPATCHED.value
    assert body["delivery_channel"] == "MOCK"
    # SLA принятия выставлен и оценён на чтении (E6, FR-6.1/6.2).
    assert body["sla"]["accept_deadline"]
    assert body["sla"]["accept_state"] in {"ON_TRACK", "AT_RISK", "BREACHED"}
    assert await _attempt_count(session, req.id) == 1
    attempt = await session.scalar(
        select(DispatchAttempt).where(DispatchAttempt.request_id == req.id)
    )
    assert attempt is not None
    assert attempt.status is DeliveryOutcome.SENT
    assert "summary" not in (attempt.provider_response or {})  # без ПДн


async def test_dispatch_no_channels_fails_dispatch(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_assigned(session, partner_id="c-nochan")
    _use_resolver(session, {})
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 200
    assert resp.json()["status"] == RequestStatus.FAILED_DISPATCH.value
    assert await _attempt_count(session, req.id) == 0


async def test_dispatch_falls_back_to_next_partner(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_assigned(session, partner_id="c-1", fallback=["c-2"])
    await _seed_channel(session, "c-1")
    await _seed_channel(session, "c-2")
    _use_resolver(session, {"c-1": DeliveryOutcome.FAILED, "c-2": DeliveryOutcome.ACK})
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == RequestStatus.DISPATCHED.value
    assert body["partner_id"] == "c-2"  # переключились на партнёра из цепочки
    assert await _attempt_count(session, req.id) == 2


async def test_dispatch_all_fail_then_failed_dispatch(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_assigned(session, partner_id="c-1", fallback=["c-2"])
    await _seed_channel(session, "c-1")
    await _seed_channel(session, "c-2")
    _use_resolver(session, {"c-1": DeliveryOutcome.FAILED, "c-2": DeliveryOutcome.FAILED})
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.json()["status"] == RequestStatus.FAILED_DISPATCH.value
    assert await _attempt_count(session, req.id) == 2


async def test_dispatch_requester_forbidden_403(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed_assigned(session, partner_id="c-1")
    req.requester_id = str(owner.user_id)
    await session.commit()
    await _seed_channel(session, "c-1")
    _use_resolver(session, {"c-1": DeliveryOutcome.SENT})
    resp = await make_client(owner).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 403


async def test_dispatch_wrong_status_409(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    operator = _principal(PrincipalKind.OPERATOR)
    req = await _seed_assigned(session, status=RequestStatus.NEW)
    _use_resolver(session, {})
    resp = await make_client(operator).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 409


async def test_dispatch_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_assigned(session, partner_id="c-1")
    req.requester_id = "other"
    await session.commit()
    stranger = _principal(PrincipalKind.REQUESTER)
    _use_resolver(session, {})
    resp = await make_client(stranger).post(f"{_BASE}/{req.id}/dispatch")
    assert resp.status_code == 404
