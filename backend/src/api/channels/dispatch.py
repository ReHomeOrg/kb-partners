"""Диспетчеризация заявки партнёру (эпик E4, FR-4.1–4.6).

M3.2b — синхронная доставка: выбор канала по priority среди активных каналов
партнёра (§9.3), доставка через адаптер, фиксация `DispatchAttempt` на КАЖДУЮ
попытку (идемпотентный ключ на попытку). Успех → DISPATCHED; провал всех каналов
текущего партнёра → следующий партнёр из `fallback_chain`; исчерпание → DISPATCHED→
FAILED_DISPATCH (FR-4.5, эскалация оператору).

В партнёрский канал уходит МИНИМАЛЬНЫЙ состав по категории (FR-4.6): номер,
категория, маскированное описание и структурированные params — без сырых ПДн.

Транзакционный outbox + Dramatiq-drainer (асинхронная durable-доставка, NFR-8) —
веха M4 (вместе с воркером); здесь доставка синхронна в рамках запроса.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.channels.enums import DeliveryOutcome
from api.channels.models import DispatchAttempt, PartnerChannelConfig
from api.channels.protocol import DeliveryPayload, DeliveryResult
from api.channels.repository import DispatchRepository
from api.channels.resolver import ChannelResolver, to_channel_config
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.requests.access import can_drive_lifecycle
from api.requests.enums import RequestStatus
from api.requests.models import ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.schemas import RequestDetail
from api.requests.service import apply_transition, build_detail

_logger = get_logger("dispatch")

_SUCCESS_OUTCOMES = frozenset(
    {DeliveryOutcome.SENT, DeliveryOutcome.DELIVERED, DeliveryOutcome.ACK}
)


class DispatchService:
    """Запуск диспетчеризации (operator/agent). Источник — ASSIGNED (§7)."""

    def __init__(self, session: AsyncSession, resolver: ChannelResolver) -> None:
        self._session = session
        self._requests = RequestRepository(session)
        self._dispatch = DispatchRepository(session)
        self._resolver = resolver

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

        apply_transition(self._session, principal, request, RequestStatus.DISPATCHED)
        delivered = await self._deliver(request)
        if not delivered:
            apply_transition(self._session, principal, request, RequestStatus.FAILED_DISPATCH)

        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        _logger.info(
            "request dispatch: number=%s delivered=%s status=%s",
            request.number,
            delivered,
            request.status.value,
        )
        return detail

    async def _deliver(self, request: ServiceRequest) -> bool:
        """Перебрать партнёра + fallback_chain × каналы по приоритету. True при успехе.

        Чтения каналов/попыток — под `no_autoflush`: незакоммиченные изменения FSM
        не должны автофлашиться промежуточными SELECT'ами (иначе MissingGreenlet в
        async; финальный commit запишет всё атомарно).
        """
        with self._session.no_autoflush:
            attempt_no = await self._dispatch.count_attempts(request.id)
            partners = [request.partner_id, *(request.fallback_chain or [])]
            for partner_id in partners:
                if partner_id is None:
                    continue
                for config in await self._dispatch.active_channels_for(partner_id):
                    attempt_no += 1
                    result = await self._attempt(request, config, attempt_no)
                    self._dispatch.add_attempt(
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
                        request.partner_id = partner_id
                        request.delivery_channel = config.channel_type.value
                        return True
        return False

    async def _attempt(
        self, request: ServiceRequest, config: PartnerChannelConfig, attempt_no: int
    ) -> DeliveryResult:
        payload = self._build_payload(request, attempt_no)
        try:
            async with self._resolver.resolve(config) as channel:
                return await channel.deliver(payload, to_channel_config(config))
        except NotImplementedError:
            # Канал без реализации (ждёт ADR) — попытка считается проваленной, идём дальше.
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": "unsupported_channel"}
            )

    @staticmethod
    def _build_payload(request: ServiceRequest, attempt_no: int) -> DeliveryPayload:
        """Минимальный состав по категории (FR-4.6): без сырых ПДн."""
        assert request.category is not None  # гарантировано проверкой в dispatch()
        params: dict[str, Any] = {}
        if request.classification is not None:
            raw_params = request.classification.get("params")
            if isinstance(raw_params, dict):
                params = raw_params
        return DeliveryPayload(
            request_id=str(request.id),
            number=request.number,
            category=request.category.value,
            summary=request.raw_input_masked,
            params=params,
            idempotency_key=f"dispatch:{request.id}:{attempt_no}",
        )
