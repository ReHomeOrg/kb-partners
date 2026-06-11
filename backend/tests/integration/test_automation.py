"""Интеграционные тесты автоматизации on_create (E6, FR-6.3): пайплайн + enqueue."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.automation.autonomy import AutonomyLevel
from api.automation.pipeline import AutomationDeps, drain_on_create_batch, run_on_create
from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.models import DispatchAttempt, PartnerChannelConfig
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.classifier.engine import ClassifierEngine
from api.classifier.provider import NullLLMProvider
from api.clients.platform.models import CollaboratorCandidate, ServiceOrderRef
from api.config import Settings
from api.matching.engine import Matcher
from api.outbox.models import OutboxMessage
from api.outbox.repository import OutboxRepository
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.requests.service import IntakeService
from api.sla.engine import SlaPolicy


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


class _FakePlatform:
    def __init__(self, candidates: list[CollaboratorCandidate]) -> None:
        self._candidates = candidates

    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        return [c for c in self._candidates if c.category == category]

    async def create_service_order(
        self, *, request_id: str, partner_id: str, category: str, idempotency_key: str
    ) -> ServiceOrderRef | None:
        return ServiceOrderRef(id="so-1", status="DRAFT")


def _candidate(cid: str) -> CollaboratorCandidate:
    return CollaboratorCandidate(
        id=cid,
        name=cid,
        category="CLEANING",
        is_active=True,
        available=True,
        rating=4.5,
        channels=("MOCK",),
    )


def _deps(
    candidates: list[CollaboratorCandidate], *, autonomy: AutonomyLevel = AutonomyLevel.DISPATCH
) -> AutomationDeps:
    settings = Settings()
    return AutomationDeps(
        engine=ClassifierEngine(NullLLMProvider()),
        confidence_threshold=settings.classifier_confidence_threshold,
        platform=_FakePlatform(candidates),
        matcher=Matcher(),
        resolver=_SentResolver(),
        policy=SlaPolicy.from_settings(settings),
        require_service_order=False,
        autonomy=autonomy,
    )


async def _seed_new(session: AsyncSession, masked: str = "нужна уборка квартиры") -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-AUTO-{uuid.uuid4().hex[:8]}",
        requester_id="u",
        channel_in=ChannelIn.WEB_FORM,
        raw_input=masked,
        raw_input_masked=masked,
        status=RequestStatus.NEW,
        access_level=AccessLevel.LOGGED,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


async def test_pipeline_classifies_assigns_dispatches(session: AsyncSession) -> None:
    req = await _seed_new(session)
    session.add(
        PartnerChannelConfig(
            collaborator_id="c-1",
            channel_type=ChannelType.MOCK,
            priority=10,
            config={},
            is_active=True,
        )
    )
    await session.commit()

    outcome = await run_on_create(session, req.id, _deps([_candidate("c-1")]))
    assert outcome == "dispatched"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None
    assert refreshed.status is RequestStatus.DISPATCHED
    assert refreshed.partner_id == "c-1"
    assert refreshed.category is Category.CLEANING
    attempts = await session.scalar(
        select(func.count())
        .select_from(DispatchAttempt)
        .where(DispatchAttempt.request_id == req.id)
    )
    assert attempts and attempts >= 1


async def _seed_channel(session: AsyncSession, collaborator_id: str = "c-1") -> None:
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


async def test_pipeline_rerun_is_idempotent(session: AsyncSession) -> None:
    req = await _seed_new(session)
    await _seed_channel(session)
    deps = _deps([_candidate("c-1")])
    first = await run_on_create(session, req.id, deps)
    # Повтор после visibility-timeout: classify уже пройдена (409 толерируется).
    second = await run_on_create(session, req.id, deps)
    assert first == "dispatched"
    assert second == "dispatched"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.DISPATCHED


async def test_drain_on_create_batch_runs_pipeline(session: AsyncSession) -> None:
    req = await _seed_new(session)
    await _seed_channel(session)
    OutboxRepository(session).enqueue("automation_on_create", {"request_id": str(req.id)})
    await session.commit()

    processed = await drain_on_create_batch(
        session, _deps([_candidate("c-1")]), settings=Settings()
    )
    assert processed == 1
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.DISPATCHED


async def test_autonomy_classify_only_stops_at_classified(session: AsyncSession) -> None:
    req = await _seed_new(session)
    await _seed_channel(session)
    outcome = await run_on_create(
        session, req.id, _deps([_candidate("c-1")], autonomy=AutonomyLevel.CLASSIFY)
    )
    assert outcome == "classified"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.CLASSIFIED


async def test_autonomy_assign_stops_at_assigned(session: AsyncSession) -> None:
    req = await _seed_new(session)
    await _seed_channel(session)
    outcome = await run_on_create(
        session, req.id, _deps([_candidate("c-1")], autonomy=AutonomyLevel.ASSIGN)
    )
    assert outcome == "assigned"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.ASSIGNED


async def test_pipeline_low_confidence_stops_at_needs_review(session: AsyncSession) -> None:
    req = await _seed_new(session, masked="просто текст без признаков")
    outcome = await run_on_create(session, req.id, _deps([_candidate("c-1")]))
    assert outcome == "needs_review"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.NEEDS_REVIEW


async def test_pipeline_no_partner_stops_after_classification(session: AsyncSession) -> None:
    req = await _seed_new(session)
    outcome = await run_on_create(session, req.id, _deps([]))  # кандидатов нет
    assert outcome == "no_partner"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.CLASSIFIED


async def test_intake_enqueues_automation_when_enabled(session: AsyncSession) -> None:
    from api.auth.principal import Principal, PrincipalKind
    from api.requests.schemas import RequestCreate

    service = IntakeService(session, automation_on_create=True)
    principal = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)
    request, created = await service.create_from_form(
        principal, RequestCreate(raw_input="уборка"), None
    )
    assert created
    count = await session.scalar(
        select(func.count())
        .select_from(OutboxMessage)
        .where(OutboxMessage.kind == "automation_on_create")
    )
    assert count == 1
