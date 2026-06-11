"""Интеграционные тесты time_based-движка (E6, FR-4.4/4.5/6.3): авто-fallback по SLA."""

from __future__ import annotations

import contextlib
import datetime
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.automation.timers import (
    PARTNER_FALLBACK_KIND,
    drain_partner_fallback_batch,
    redispatch_to_next,
    scan_accept_timeouts,
)
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.models import PartnerChannelConfig
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.config import Settings
from api.outbox.models import OutboxMessage, OutboxStatus
from api.outbox.repository import OutboxRepository
from api.requests import partner as partner_module
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.requests.partner import advance_partner_status
from api.sla.engine import SlaPolicy

_ENABLED = Settings(automation_time_based_enabled=True)
_POLICY = SlaPolicy.from_settings(_ENABLED)


class _SentChannel:
    channel_type = ChannelType.MOCK

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        return DeliveryResult(outcome=DeliveryOutcome.SENT, provider_response={"ok": True})

    async def parse_inbound(
        self, payload: dict[str, object], config: ChannelConfig
    ) -> StatusUpdate | None:
        return None

    async def healthcheck(self, config: ChannelConfig) -> Health:
        return Health(status=HealthStatus.HEALTHY)


class _SentResolver:
    def resolve(
        self, config: PartnerChannelConfig
    ) -> contextlib.AbstractAsyncContextManager[_SentChannel]:
        @contextlib.asynccontextmanager
        async def _ctx() -> AsyncIterator[_SentChannel]:
            yield _SentChannel()

        return _ctx()


async def _seed_dispatched(
    session: AsyncSession,
    *,
    partner_id: str,
    fallback_chain: list[str],
    accept_deadline: datetime.datetime,
    channels_for: list[str],
) -> ServiceRequest:
    now = datetime.datetime.now(datetime.UTC)
    request = ServiceRequest(
        number=f"RQ-S-{uuid.uuid4().hex[:10]}",
        requester_id="u",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="уборка",
        raw_input_masked="уборка",
        status=RequestStatus.DISPATCHED,
        access_level=AccessLevel.LOGGED,
        category=Category.CLEANING,
        partner_id=partner_id,
        fallback_chain=fallback_chain,
        dispatched_at=now,
        sla={"accept_deadline": accept_deadline.isoformat(), "paused_intervals": []},
        custom_fields={},
    )
    session.add(request)
    for cid in channels_for:
        session.add(
            PartnerChannelConfig(
                collaborator_id=cid,
                channel_type=ChannelType.MOCK,
                priority=10,
                config={},
                is_active=True,
            )
        )
    await session.commit()
    return request


async def test_breached_redispatches_to_next_partner(session: AsyncSession) -> None:
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=past,
        channels_for=["c-2"],
    )
    processed = await scan_accept_timeouts(
        session, resolver=_SentResolver(), policy=_POLICY, settings=_ENABLED
    )
    assert processed == 1
    await session.refresh(request)
    # Перешли к следующему партнёру, цепочка исчерпана, заявка снова DISPATCHED.
    assert request.status is RequestStatus.DISPATCHED
    assert request.partner_id == "c-2"
    assert request.fallback_chain == []
    # Поставлен новый дедлайн принятия для нового партнёра.
    assert request.sla is not None and request.sla.get("accept_deadline") is not None


async def test_breached_without_chain_fails_dispatch(session: AsyncSession) -> None:
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    request = await _seed_dispatched(
        session, partner_id="c-1", fallback_chain=[], accept_deadline=past, channels_for=[]
    )
    processed = await scan_accept_timeouts(
        session, resolver=_SentResolver(), policy=_POLICY, settings=_ENABLED
    )
    assert processed == 1
    await session.refresh(request)
    assert request.status is RequestStatus.FAILED_DISPATCH


async def test_not_breached_is_untouched(session: AsyncSession) -> None:
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=4)
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=future,
        channels_for=["c-2"],
    )
    processed = await scan_accept_timeouts(
        session, resolver=_SentResolver(), policy=_POLICY, settings=_ENABLED
    )
    assert processed == 0
    await session.refresh(request)
    assert request.status is RequestStatus.DISPATCHED
    assert request.partner_id == "c-1"


async def test_scan_inert_when_disabled(session: AsyncSession) -> None:
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=1)
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=past,
        channels_for=["c-2"],
    )
    # Дефолтные настройки → time_based выключен, скан инертен.
    processed = await scan_accept_timeouts(
        session, resolver=_SentResolver(), policy=_POLICY, settings=Settings()
    )
    assert processed == 0
    await session.refresh(request)
    assert request.status is RequestStatus.DISPATCHED
    assert request.partner_id == "c-1"


async def _partner_fallback_count(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.kind == PARTNER_FALLBACK_KIND)
    )
    return int((await session.execute(stmt)).scalar_one())


async def test_rejection_enqueues_partner_fallback(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # FR-5.3: отклонение партнёром → durable-задача авто-fallback (time_based включён).
    monkeypatch.setattr(partner_module, "get_settings", lambda: _ENABLED)
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=datetime.datetime.now(datetime.UTC),
        channels_for=["c-2"],
    )
    principal = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.PARTNER, partner_id="c-1")
    advance_partner_status(session, principal, request, "rejected", _POLICY)
    await session.commit()
    assert request.status is RequestStatus.MATCHING
    assert await _partner_fallback_count(session) == 1


async def test_rejection_no_enqueue_when_disabled(session: AsyncSession) -> None:
    # Дефолт (time_based off) → отклонение оставляет заявку в MATCHING без задачи.
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=datetime.datetime.now(datetime.UTC),
        channels_for=["c-2"],
    )
    principal = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.PARTNER, partner_id="c-1")
    advance_partner_status(session, principal, request, "rejected", _POLICY)
    await session.commit()
    assert request.status is RequestStatus.MATCHING
    assert await _partner_fallback_count(session) == 0


async def test_partner_fallback_drain_redispatches(session: AsyncSession) -> None:
    # Заявка отклонена → уже в MATCHING (partner c-1), цепочка ["c-2"]; дрейн откатывает.
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=["c-2"],
        accept_deadline=datetime.datetime.now(datetime.UTC),
        channels_for=["c-2"],
    )
    request.status = RequestStatus.MATCHING
    OutboxRepository(session).enqueue(PARTNER_FALLBACK_KIND, {"request_id": str(request.id)})
    await session.commit()

    processed = await drain_partner_fallback_batch(
        session, resolver=_SentResolver(), policy=_POLICY, settings=_ENABLED
    )
    assert processed == 1
    await session.refresh(request)
    assert request.status is RequestStatus.DISPATCHED
    assert request.partner_id == "c-2"
    assert request.fallback_chain == []
    done = await session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(
            OutboxMessage.kind == PARTNER_FALLBACK_KIND, OutboxMessage.status == OutboxStatus.DONE
        )
    )
    assert done == 1


async def test_redispatch_exhausted_stays_in_matching(session: AsyncSession) -> None:
    # Цепочка исчерпана → эскалация, заявка остаётся в MATCHING (human-handoff).
    request = await _seed_dispatched(
        session,
        partner_id="c-1",
        fallback_chain=[],
        accept_deadline=datetime.datetime.now(datetime.UTC),
        channels_for=[],
    )
    request.status = RequestStatus.MATCHING
    await session.commit()
    outcome = await redispatch_to_next(session, request, resolver=_SentResolver(), policy=_POLICY)
    assert outcome == "exhausted"
    assert request.status is RequestStatus.MATCHING
