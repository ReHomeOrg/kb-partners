"""Интеграционные тесты ретенции ПДн (NFR-12, 152-ФЗ): обезличивание raw_input."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.requests.enums import AccessLevel, ChannelIn, HistoryAction, RequestStatus
from api.requests.models import RequestHistory, ServiceRequest
from api.retention.worker import anonymize_expired_raw_input

_ENABLED = Settings(retention_worker_enabled=True, raw_input_retention_days=180)


async def _seed(session: AsyncSession, *, age_days: int) -> ServiceRequest:
    created = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=age_days)
    request = ServiceRequest(
        number=f"RQ-R-{uuid.uuid4().hex[:10]}",
        requester_id="u",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="Иван Петров, +7 900 111-22-33, ул. Ленина 1",
        raw_input_masked="[имя], [телефон], [адрес]",
        status=RequestStatus.PAID,
        access_level=AccessLevel.LOGGED,
        custom_fields={},
    )
    session.add(request)
    await session.flush()
    # created_at — server_default; выставляем явно в прошлое для теста ретенции.
    request.created_at = created
    await session.commit()
    return request


async def _anonymized_history(session: AsyncSession, request_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(RequestHistory)
        .where(
            RequestHistory.request_id == request_id,
            RequestHistory.action == HistoryAction.ANONYMIZED,
        )
    )
    return int((await session.execute(stmt)).scalar_one())


async def test_expired_raw_input_anonymized(session: AsyncSession) -> None:
    request = await _seed(session, age_days=200)  # старше 180 дней
    processed = await anonymize_expired_raw_input(session, settings=_ENABLED)
    assert processed == 1
    await session.refresh(request)
    # Сырой ПДн стёрт до маски; маска (PII-free) сохранена.
    assert request.raw_input == request.raw_input_masked
    assert "+7 900" not in request.raw_input
    assert await _anonymized_history(session, request.id) == 1


async def test_idempotent_second_run(session: AsyncSession) -> None:
    await _seed(session, age_days=200)
    assert await anonymize_expired_raw_input(session, settings=_ENABLED) == 1
    # Повтор — заявка уже обезличена (raw_input == masked) → не попадает в выборку.
    assert await anonymize_expired_raw_input(session, settings=_ENABLED) == 0


async def test_recent_request_untouched(session: AsyncSession) -> None:
    request = await _seed(session, age_days=10)  # в пределах ретенции
    processed = await anonymize_expired_raw_input(session, settings=_ENABLED)
    assert processed == 0
    await session.refresh(request)
    assert "+7 900" in request.raw_input


async def test_inert_when_disabled(session: AsyncSession) -> None:
    request = await _seed(session, age_days=200)
    processed = await anonymize_expired_raw_input(session, settings=Settings())
    assert processed == 0
    await session.refresh(request)
    assert "+7 900" in request.raw_input
