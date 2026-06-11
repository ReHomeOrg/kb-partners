"""Приёмка, спор, оплата (эпик E7, FR-7.1–7.3).

Приёмку подтверждает пользователь (или оператор) → ACCEPTED_BY_USER. Спор →
DISPUTE и (если контур претензий сконфигурирован) порождает COMPENSATION в
kb-support, ссылка — в `claim_ref`/`dispute_id`. Деньги модуль НЕ считает: хранит
только ссылки контура (`amount_ref`/`escrow_ref`), достижение расчёта → PAID
(подтверждается платёжным контуром rehome.one, SERVICE).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.clients.rehome.protocol import RehomeOneClient
from api.clients.support.protocol import KbSupportClient
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.requests.access import can_user_action
from api.requests.enums import RequestStatus
from api.requests.models import ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.schemas import RequestDetail, SettlementConfirm
from api.requests.service import apply_transition, build_detail

_logger = get_logger("requests.acceptance")


class AcceptanceService:
    """Приёмка пользователем, открытие спора, подтверждение расчёта (E7)."""

    def __init__(
        self,
        session: AsyncSession,
        support: KbSupportClient,
        rehome: RehomeOneClient,
        *,
        enable_claims: bool = False,
        enable_settlement: bool = False,
    ) -> None:
        self._session = session
        self._repo = RequestRepository(session)
        self._support = support
        self._rehome = rehome
        self._enable_claims = enable_claims
        self._enable_settlement = enable_settlement

    async def accept(self, principal: Principal, request_id: uuid.UUID) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not can_user_action(principal):
            raise ProblemException.forbidden(detail="Acceptance not allowed for subject")
        # DONE→ACCEPTED_BY_USER (FR-7.1); иной статус → 409.
        apply_transition(self._session, principal, request, RequestStatus.ACCEPTED_BY_USER)
        if self._enable_settlement:
            # Триггер расчёта/escrow в контуре rehome.one; модуль хранит лишь ссылки.
            ref = await self._rehome.trigger_settlement(
                request_id=str(request.id),
                service_order_id=request.service_order_id,
                idempotency_key=f"settle:{request.id}",
            )
            if ref is not None:
                request.amount_ref = ref.amount_ref
                request.escrow_ref = ref.escrow_ref
        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        _logger.info("request accepted by user: number=%s", request.number)
        return detail

    async def confirm_settlement(
        self, principal: Principal, request_id: uuid.UUID, body: SettlementConfirm
    ) -> RequestDetail:
        """Платёжный контур подтвердил расчёт → PAID (FR-7.3, SERVICE-only)."""
        stmt = select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
        request = (await self._session.execute(stmt)).scalar_one_or_none()
        if request is None:
            raise ProblemException.not_found()
        # ACCEPTED_BY_USER→PAID (§7); иной статус → 409.
        apply_transition(self._session, principal, request, RequestStatus.PAID)
        if body.amount_ref is not None:
            request.amount_ref = body.amount_ref
        if body.escrow_ref is not None:
            request.escrow_ref = body.escrow_ref
        detail = build_detail(principal, request)
        await self._session.commit()
        _logger.info("request settled (PAID): number=%s", request.number)
        return detail

    async def dispute(
        self, principal: Principal, request_id: uuid.UUID, reason: str
    ) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not can_user_action(principal):
            raise ProblemException.forbidden(detail="Dispute not allowed for subject")
        # DONE|ACCEPTED_BY_USER→DISPUTE (FR-7.2); иной статус → 409.
        apply_transition(self._session, principal, request, RequestStatus.DISPUTE)
        request.custom_fields = {**request.custom_fields, "dispute": {"reason": reason}}
        if self._enable_claims:
            ref = await self._support.create_compensation_claim(
                request_id=str(request.id),
                requester_id=request.requester_id,
                reason=reason,
                idempotency_key=f"dispute:{request.id}",
            )
            if ref is not None:
                request.dispute_id = ref.id
                request.claim_ref = ref.id
        detail = build_detail(principal, request)  # до commit
        await self._session.commit()
        _logger.info("request disputed: number=%s claim=%s", request.number, request.claim_ref)
        return detail
