"""Сервис приёма заявок (эпик E1, FR-1.1–FR-1.6).

Инварианты:
- **Маскировка ПДн (FR-1.6):** `raw_input_masked = mask_pii(raw_input)` формируется
  при приёме, ДО любых логов и LLM-вызовов; наружу `raw_input` не отдаётся.
- **Идемпотентность приёма:** дедуп по `idempotency_key` (Idempotency-Key для
  `POST /requests`; `chat:<session>` / `ticket:<id>` для from-chat/from-ticket).
  Повторная доставка возвращает ту же заявку (created=False), не создаёт дубль.
  Гонка прикрыта частичным unique-индексом + повторным чтением на IntegrityError.
- **Аудит:** создание заявки → запись `RequestHistory(action=CREATED)` с актором
  (`on_behalf_of` пользователя, иначе субъект). NOT NULL `actor_id`.
- **Защита канала:** `channel_in` выводится бэкендом (не из тела `POST /requests`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.observability.pii_mask import mask_pii
from api.requests.enums import AccessLevel, ChannelIn, HistoryAction, RequestStatus
from api.requests.models import RequestHistory, ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.schemas import FromChatCreate, FromTicketCreate, RequestCreate

_logger = get_logger("requests.intake")


class IntakeService:
    """Создание заявок из каналов приёма E1. Возвращает `(заявка, создана?)`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = RequestRepository(session)

    async def create_from_form(
        self, principal: Principal, body: RequestCreate, idempotency_key: str | None
    ) -> tuple[ServiceRequest, bool]:
        """`POST /requests` — ЛК-форма (WEB_FORM) или m2m-инициатор (API)."""
        channel_in = (
            ChannelIn.API if principal.kind is PrincipalKind.SERVICE else ChannelIn.WEB_FORM
        )
        requester_id = self._resolve_requester(principal, body.requester_id)
        return await self._intake(
            principal=principal,
            requester_id=requester_id,
            raw_input=body.raw_input,
            channel_in=channel_in,
            source_ref=body.source_ref,
            booking_id=body.booking_id,
            premises_id=body.premises_id,
            idempotency_key=idempotency_key,
        )

    async def create_from_chat(
        self, principal: Principal, body: FromChatCreate
    ) -> tuple[ServiceRequest, bool]:
        """`POST /requests/from-chat` — инициация из AI-чата (AI_CHAT), идемп. по сессии."""
        source_ref: dict[str, Any] = {"chat_session_id": body.chat_session_id}
        if body.transcript is not None:
            source_ref["transcript"] = body.transcript
        return await self._intake(
            principal=principal,
            requester_id=body.requester_id,
            raw_input=body.raw_input,
            channel_in=ChannelIn.AI_CHAT,
            source_ref=source_ref,
            booking_id=body.booking_id,
            premises_id=body.premises_id,
            idempotency_key=f"chat:{body.chat_session_id}",
        )

    async def create_from_ticket(
        self, principal: Principal, body: FromTicketCreate
    ) -> tuple[ServiceRequest, bool]:
        """`POST /requests/from-ticket` — эскалация из тикета (SUPPORT_TICKET), обр. ссылка."""
        return await self._intake(
            principal=principal,
            requester_id=body.requester_id,
            raw_input=body.raw_input,
            channel_in=ChannelIn.SUPPORT_TICKET,
            source_ref={"ticket_id": body.ticket_id},
            booking_id=body.booking_id,
            premises_id=body.premises_id,
            idempotency_key=f"ticket:{body.ticket_id}",
        )

    def _resolve_requester(self, principal: Principal, provided: str | None) -> str:
        """Определить `requester_id` без подмены: заявитель — только от своего имени."""
        if principal.kind is PrincipalKind.REQUESTER:
            return str(principal.user_id)
        if provided:
            return provided
        if principal.on_behalf_of is not None:
            return str(principal.on_behalf_of)
        if principal.kind is PrincipalKind.SERVICE:
            raise ProblemException.bad_request(detail="requester_id is required for service intake")
        return str(principal.user_id)

    async def _intake(
        self,
        *,
        principal: Principal,
        requester_id: str,
        raw_input: str,
        channel_in: ChannelIn,
        source_ref: dict[str, Any] | None,
        booking_id: str | None,
        premises_id: str | None,
        idempotency_key: str | None,
    ) -> tuple[ServiceRequest, bool]:
        if idempotency_key is not None:
            existing = await self._repo.get_by_idempotency_key(idempotency_key)
            if existing is not None:
                _logger.info(
                    "intake idempotent replay: number=%s channel=%s",
                    existing.number,
                    channel_in.value,
                )
                return existing, False

        # ПДн-маскирование ДО любого лога/LLM (FR-1.6).
        masked = mask_pii(raw_input)
        number = await self._repo.next_number()
        request = ServiceRequest(
            number=number,
            requester_id=requester_id,
            channel_in=channel_in,
            source_ref=source_ref,
            raw_input=raw_input,
            raw_input_masked=masked,
            booking_id=booking_id,
            premises_id=premises_id,
            status=RequestStatus.NEW,
            access_level=AccessLevel.LOGGED,
            idempotency_key=idempotency_key,
        )
        self._repo.add(request)
        try:
            await self._session.flush()
        except IntegrityError:
            # Гонка по idempotency_key: один из конкурентов проиграл unique-индекс.
            await self._session.rollback()
            if idempotency_key is not None:
                existing = await self._repo.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return existing, False
            raise

        actor_id = principal.on_behalf_of or principal.user_id
        self._session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=actor_id,
                action=HistoryAction.CREATED,
                to_value=RequestStatus.NEW.value,
            )
        )
        await self._session.commit()
        _logger.info(
            "request intake created: number=%s channel=%s status=%s",
            request.number,
            channel_in.value,
            request.status.value,
        )
        return request, True
