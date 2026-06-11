"""Контекст заявителя из rehome.one (E9, FR-9.1; §11.1 requester-context).

Tool для оператора/агента: User/Premises/Booking по заявке. Видимость заявки —
по двухконтурности (get_visible); доступ к контексту — оператор/агент (не заявитель/
партнёр). Контекст содержит ПДн заявителя — отдаётся только привилегированным ролям.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.clients.rehome.protocol import RehomeOneClient
from api.errors import ProblemException
from api.requests.repository import RequestRepository
from api.requests.schemas import RequesterContextResponse


class ContextService:
    """Получение контекста заявителя из контура rehome.one (E9)."""

    def __init__(self, session: AsyncSession, rehome: RehomeOneClient) -> None:
        self._repo = RequestRepository(session)
        self._rehome = rehome

    async def get_requester_context(
        self, principal: Principal, request_id: uuid.UUID
    ) -> RequesterContextResponse:
        request = await self._repo.get_visible(principal, request_id)
        if request is None:
            raise ProblemException.not_found()
        if not (principal.is_operator or principal.is_agent):
            raise ProblemException.forbidden(detail="Requester context is operator/agent only")
        ctx = await self._rehome.get_requester_context(
            requester_id=request.requester_id,
            premises_id=request.premises_id,
            booking_id=request.booking_id,
        )
        if ctx is None:
            # Контур недоступен/инертен — пустой контекст (graceful), без ошибки.
            return RequesterContextResponse()
        return RequesterContextResponse(
            user_display_name=ctx.user_display_name,
            user_phone=ctx.user_phone,
            user_email=ctx.user_email,
            premises_address=ctx.premises_address,
            booking_status=ctx.booking_status,
        )
