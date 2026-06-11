"""Диспетчеризация заявки партнёру (эпик E4, FR-4.1–4.6) на transactional outbox (NFR-8).

Endpoint enqueue'ит outbox-сообщение `dispatch` В ОДНОЙ транзакции с переходом
ASSIGNED→DISPATCHED (commit-1, durable), затем best-effort СИНХРОННО дрейнит его
(commit-2: доставка + DispatchAttempt + статус). Если процесс упал между коммитами —
сообщение остаётся PENDING и его добирает Dramatiq-воркер (`drain_dispatch_batch`).
Повторная доставка идемпотентна (Idempotency-Key на попытку → дедуп у партнёра).

Выбор канала по priority среди активных каналов партнёра (§9.3); провал всех каналов
партнёра → следующий из `fallback_chain`; исчерпание → DISPATCHED→FAILED_DISPATCH
(FR-4.5). В канал — минимальный состав по категории (FR-4.6), без сырых ПДн.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import DISPATCH_ACTOR_ID
from api.channels.enums import DeliveryOutcome
from api.channels.models import DispatchAttempt, PartnerChannelConfig
from api.channels.protocol import DeliveryPayload, DeliveryResult
from api.channels.repository import DispatchRepository
from api.channels.resolver import ChannelResolver, to_channel_config
from api.config import Settings
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.outbox.models import OutboxMessage
from api.outbox.repository import OutboxRepository
from api.requests.access import can_drive_lifecycle
from api.requests.enums import RequestStatus
from api.requests.models import ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.schemas import RequestDetail
from api.requests.service import apply_transition, build_detail
from api.sla.engine import SlaPolicy

_logger = get_logger("dispatch")

_OUTBOX_KIND = "dispatch"
_SUCCESS_OUTCOMES = frozenset(
    {DeliveryOutcome.SENT, DeliveryOutcome.DELIVERED, DeliveryOutcome.ACK}
)
# Системный субъект для атрибуции FSM-переходов диспетчера (drain — system-driven).
_DISPATCH_PRINCIPAL = Principal(user_id=DISPATCH_ACTOR_ID, kind=PrincipalKind.SERVICE)


def _build_payload(request: ServiceRequest, attempt_no: int) -> DeliveryPayload:
    """Минимальный состав по категории (FR-4.6): без сырых ПДн."""
    assert request.category is not None
    params: dict[str, Any] = {}
    if request.classification is not None:
        raw = request.classification.get("params")
        if isinstance(raw, dict):
            params = raw
    return DeliveryPayload(
        request_id=str(request.id),
        number=request.number,
        category=request.category.value,
        summary=request.raw_input_masked,
        params=params,
        idempotency_key=f"dispatch:{request.id}:{attempt_no}",
    )


async def _attempt_delivery(
    resolver: ChannelResolver,
    request: ServiceRequest,
    config: PartnerChannelConfig,
    attempt_no: int,
) -> DeliveryResult:
    payload = _build_payload(request, attempt_no)
    try:
        async with resolver.resolve(config) as channel:
            return await channel.deliver(payload, to_channel_config(config))
    except NotImplementedError:
        return DeliveryResult(
            outcome=DeliveryOutcome.FAILED, provider_response={"error": "unsupported_channel"}
        )


async def execute_dispatch(
    session: AsyncSession, request: ServiceRequest, *, resolver: ChannelResolver, policy: SlaPolicy
) -> bool:
    """Доставить заявку (перебор партнёр+fallback × каналы), записать попытки. True при успехе.

    Чтения под `no_autoflush` (FSM-изменения не должны автофлашиться промежуточными
    SELECT'ами → MissingGreenlet). Провал всех → DISPATCHED→FAILED_DISPATCH.
    """
    dispatch_repo = DispatchRepository(session)
    chosen_partner: str | None = None
    chosen_channel: str | None = None
    with session.no_autoflush:
        attempt_no = await dispatch_repo.count_attempts(request.id)
        partners = [request.partner_id, *(request.fallback_chain or [])]
        for partner_id in partners:
            if partner_id is None:
                continue
            for config in await dispatch_repo.active_channels_for(partner_id):
                attempt_no += 1
                result = await _attempt_delivery(resolver, request, config, attempt_no)
                dispatch_repo.add_attempt(
                    DispatchAttempt(
                        request_id=request.id,
                        channel_type=config.channel_type,
                        attempt_no=attempt_no,
                        status=result.outcome,
                        provider_response=result.provider_response,
                        idempotency_key=f"dispatch:{request.id}:{attempt_no}",
                    )
                )
                if result.outcome in _SUCCESS_OUTCOMES:
                    chosen_partner = partner_id
                    chosen_channel = config.channel_type.value
                    break
            if chosen_partner is not None:
                break

    if chosen_partner is not None:
        request.partner_id = chosen_partner
        request.delivery_channel = chosen_channel
        assert request.dispatched_at is not None
        sla = policy.set_accept_deadline(request.sla, request.dispatched_at)
        sla["accept_started_at"] = request.dispatched_at.isoformat()
        request.sla = sla
        return True

    apply_transition(session, _DISPATCH_PRINCIPAL, request, RequestStatus.FAILED_DISPATCH)
    return False


async def _load_request(session: AsyncSession, request_id: uuid.UUID) -> ServiceRequest | None:
    stmt = select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


class DispatchService:
    """Запуск диспетчеризации (operator/agent). Источник — ASSIGNED (§7)."""

    def __init__(self, session: AsyncSession, resolver: ChannelResolver, policy: SlaPolicy) -> None:
        self._session = session
        self._requests = RequestRepository(session)
        self._outbox = OutboxRepository(session)
        self._resolver = resolver
        self._policy = policy

    async def dispatch(self, principal: Principal, request_id: uuid.UUID) -> RequestDetail:
        request = await self._requests.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not can_drive_lifecycle(principal):
            raise ProblemException.forbidden(detail="Dispatch not allowed for subject")
        if request.status is not RequestStatus.ASSIGNED:
            raise ProblemException.conflict(
                detail=f"Dispatch not allowed in status {request.status.value}"
            )
        if request.partner_id is None or request.category is None:
            raise ProblemException.conflict(detail="Request must be assigned and classified")

        # commit-1: переход + постановка в outbox атомарно (durable, NFR-8).
        apply_transition(self._session, principal, request, RequestStatus.DISPATCHED)
        message = self._outbox.enqueue(_OUTBOX_KIND, {"request_id": str(request.id)})
        await self._session.flush()
        outbox_id = message.id
        await self._session.commit()

        # commit-2: best-effort синхронный дрейн (упадёт — добёрет воркер).
        await self._drain(outbox_id)

        refreshed = await self._requests.get_visible(principal, request_id)
        assert refreshed is not None
        return build_detail(principal, refreshed)

    async def _drain(self, outbox_id: uuid.UUID) -> None:
        message = await self._outbox.get_for_update(outbox_id)
        if message is None or message.processed_at is not None:
            return
        await drain_dispatch_message(
            self._session, message, resolver=self._resolver, policy=self._policy
        )
        await self._session.commit()


async def drain_dispatch_message(
    session: AsyncSession,
    message: OutboxMessage,
    *,
    resolver: ChannelResolver,
    policy: SlaPolicy,
) -> None:
    """Обработать одно outbox-сообщение `dispatch`: доставка + завершение сообщения.

    Не коммитит (коммит — у вызывающего). Неожиданная ошибка пробрасывается, чтобы
    caller пометил retry; «обычный» провал доставки — это FAILED_DISPATCH, не ошибка.
    """
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    raw_id = message.payload.get("request_id")
    request = await _load_request(session, uuid.UUID(str(raw_id))) if raw_id else None
    if request is None:
        repo.mark_done(message, now)  # заявки нет — нечего доставлять, закрываем
        return
    delivered = await execute_dispatch(session, request, resolver=resolver, policy=policy)
    repo.mark_done(message, now)
    _logger.info("dispatch drained: number=%s delivered=%s", request.number, delivered)


async def drain_dispatch_batch(
    session: AsyncSession, *, resolver: ChannelResolver, policy: SlaPolicy, settings: Settings
) -> int:
    """Воркерный дрейн пачки PENDING `dispatch`-сообщений. Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(kind=_OUTBOX_KIND, now=now, limit=settings.outbox_batch_size)
    processed = 0
    for message in batch:
        try:
            await drain_dispatch_message(session, message, resolver=resolver, policy=policy)
        except Exception as exc:  # noqa: BLE001 — любая инфраошибка → backoff-повтор
            delay = settings.outbox_retry_base_seconds * (2 ** (message.attempts - 1))
            repo.mark_failed_or_retry(
                message,
                error=f"{type(exc).__name__}: {exc}",
                now=now,
                max_attempts=settings.outbox_max_attempts,
                retry_at=now + datetime.timedelta(seconds=delay),
            )
        processed += 1
    await session.commit()
    return processed
