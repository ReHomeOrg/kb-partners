"""Ответ партнёра по заявке (эпик E10 портал LIGHT, FR-10.2).

Партнёр принимает/отклоняет/двигает статус своей назначенной заявки — через
аутентифицированный API портала (PARTNER JWT), параллельно каналу inbound (E5).
Маппинг статуса партнёра на FSM — общий с inbound (`advance_partner_status`).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.config import get_settings
from api.errors import ProblemException
from api.outbox.repository import OutboxRepository
from api.requests.enums import AuthorType, RequestStatus
from api.requests.models import RequestMessage, ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.schemas import PartnerResponse, RequestDetail
from api.requests.service import apply_transition, build_detail
from api.sla.engine import SlaPolicy

# Статус партнёра → целевой статус FSM (§7, FR-5.3/10.2).
PARTNER_STATUS_TARGET: dict[str, RequestStatus] = {
    "accepted": RequestStatus.ACCEPTED,
    "rejected": RequestStatus.MATCHING,
    "in_progress": RequestStatus.IN_PROGRESS,
    "done": RequestStatus.DONE,
}


def advance_partner_status(
    session: AsyncSession,
    principal: Principal,
    request: ServiceRequest,
    partner_status: str,
    policy: SlaPolicy,
) -> None:
    """Перевести заявку по статусу партнёра (общая логика inbound и портала).

    Неизвестный статус → 422; запрещённый переход → 409; уже в целевом → no-op
    (идемпотентно). При ACCEPTED стартует SLA выполнения (FR-6.1).
    """
    target = PARTNER_STATUS_TARGET.get(partner_status.lower())
    if target is None:
        raise ProblemException.unprocessable(detail=f"Unknown partner status: {partner_status}")
    if target is request.status:
        return
    apply_transition(session, principal, request, target)
    if target is RequestStatus.ACCEPTED:
        assert request.accepted_at is not None  # проставлен apply_transition(ACCEPTED)
        sla = policy.set_perform_deadline(request.sla, request.accepted_at)
        sla["perform_started_at"] = request.accepted_at.isoformat()
        request.sla = sla
    elif target is RequestStatus.MATCHING and get_settings().automation_time_based_enabled:
        # FR-5.3: отклонение партнёром → авто-fallback на следующего из цепочки.
        # Ставим durable-задачу (как accept-timeout); воркер передиспетчеризует.
        # Локальный импорт — разрывает цикл partner↔timers (timers тянет dispatch/service).
        from api.automation.timers import PARTNER_FALLBACK_KIND

        OutboxRepository(session).enqueue(PARTNER_FALLBACK_KIND, {"request_id": str(request.id)})


class PartnerService:
    """API портала партнёра LIGHT (E10): ответ по своей назначенной заявке."""

    def __init__(self, session: AsyncSession, policy: SlaPolicy) -> None:
        self._session = session
        self._repo = RequestRepository(session)
        self._policy = policy

    async def respond(
        self, principal: Principal, request_id: uuid.UUID, body: PartnerResponse
    ) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not principal.is_partner:
            raise ProblemException.forbidden(detail="Partner portal is for partners only")
        advance_partner_status(self._session, principal, request, body.status, self._policy)
        if body.message is not None:
            self._session.add(
                RequestMessage(
                    request_id=request.id,
                    author_type=AuthorType.PARTNER,
                    author_id=principal.partner_id,
                    is_internal=False,
                    text=body.message,
                )
            )
        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        return detail
