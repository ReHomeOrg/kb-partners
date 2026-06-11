"""Интеграционные тесты transactional outbox (NFR-8): репозиторий + воркерный дрейн."""

from __future__ import annotations

import contextlib
import datetime
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.dispatch import drain_dispatch_batch
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.models import DispatchAttempt, PartnerChannelConfig
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
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.sla.engine import SlaPolicy

_NOW = datetime.datetime(2026, 6, 11, 12, 0, tzinfo=datetime.UTC)


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


async def test_enqueue_and_claim_batch(session: AsyncSession) -> None:
    repo = OutboxRepository(session)
    # available_at задаём явно (server_default=func.now() — реальные часы БД, тест бы
    # зависел от стенного времени относительно фиксированного _NOW).
    for payload in ({"a": 1}, {"a": 2}):
        repo.enqueue("dispatch", payload).available_at = _NOW
    await session.commit()
    claimed = await repo.claim_batch(kind="dispatch", now=_NOW, limit=10)
    assert len(claimed) == 2
    assert all(m.status is OutboxStatus.PROCESSING and m.attempts == 1 for m in claimed)


async def test_claim_skips_future_available_at(session: AsyncSession) -> None:
    repo = OutboxRepository(session)
    msg = repo.enqueue("dispatch", {})
    msg.available_at = _NOW + datetime.timedelta(hours=1)
    await session.commit()
    claimed = await repo.claim_batch(kind="dispatch", now=_NOW, limit=10)
    assert claimed == []


async def test_mark_failed_retries_then_fails(session: AsyncSession) -> None:
    repo = OutboxRepository(session)
    msg = repo.enqueue("dispatch", {})
    msg.attempts = 1
    repo.mark_failed_or_retry(
        msg, error="boom", now=_NOW, max_attempts=3, retry_at=_NOW + datetime.timedelta(seconds=30)
    )
    assert msg.status.value == "PENDING"  # есть ещё попытки → backoff
    msg.attempts = 3
    repo.mark_failed_or_retry(msg, error="boom", now=_NOW, max_attempts=3, retry_at=_NOW)
    assert msg.status.value == "FAILED"  # исчерпано


async def _seed_dispatched(session: AsyncSession, partner_id: str = "c-1") -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-O-{uuid.uuid4().hex[:10]}",
        requester_id="u",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="уборка",
        raw_input_masked="уборка",
        status=RequestStatus.DISPATCHED,
        access_level=AccessLevel.LOGGED,
        category=Category.CLEANING,
        partner_id=partner_id,
        dispatched_at=datetime.datetime.now(datetime.UTC),
        custom_fields={},
    )
    session.add(request)
    session.add(
        PartnerChannelConfig(
            collaborator_id=partner_id,
            channel_type=ChannelType.MOCK,
            priority=10,
            config={},
            is_active=True,
        )
    )
    await session.commit()
    return request


async def test_drain_batch_delivers_pending_message(session: AsyncSession) -> None:
    req = await _seed_dispatched(session)
    repo = OutboxRepository(session)
    repo.enqueue("dispatch", {"request_id": str(req.id)})
    await session.commit()

    processed = await drain_dispatch_batch(
        session,
        resolver=_SentResolver(),
        policy=SlaPolicy.from_settings(Settings()),
        settings=Settings(),
    )
    assert processed == 1
    done = await session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.DONE)
    )
    assert done == 1
    attempts = await session.scalar(
        select(func.count())
        .select_from(DispatchAttempt)
        .where(DispatchAttempt.request_id == req.id)
    )
    assert attempts == 1


async def test_drain_batch_missing_request_completes(session: AsyncSession) -> None:
    repo = OutboxRepository(session)
    repo.enqueue("dispatch", {"request_id": str(uuid.uuid4())})  # несуществующая заявка
    await session.commit()
    processed = await drain_dispatch_batch(
        session,
        resolver=_SentResolver(),
        policy=SlaPolicy.from_settings(Settings()),
        settings=Settings(),
    )
    assert processed == 1
    done = await session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.DONE)
    )
    assert done == 1
