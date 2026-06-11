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

import datetime
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.observability.pii_mask import mask_pii
from api.requests.access import (
    can_cancel,
    can_drive_lifecycle,
    can_see_raw_input,
    can_view_internal,
)
from api.requests.enums import (
    AccessLevel,
    AuthorType,
    ChannelIn,
    HistoryAction,
    RequestStatus,
)
from api.requests.fsm import allowed_transitions, ensure_transition
from api.requests.models import RequestHistory, RequestMessage, ServiceRequest
from api.requests.pagination import decode_cursor, encode_cursor
from api.requests.repository import RequestListFilters, RequestRepository
from api.requests.schemas import (
    FromChatCreate,
    FromTicketCreate,
    MessageCreate,
    MessageRead,
    RequestCreate,
    RequestDetail,
    RequestListResponse,
    RequestRead,
    TransitionRequest,
)

_logger = get_logger("requests.intake")

# Список → таймстемп жизненного цикла, проставляемый при входе в статус (§6.1).
_STATUS_TIMESTAMP: dict[RequestStatus, str] = {
    RequestStatus.DISPATCHED: "dispatched_at",
    RequestStatus.ACCEPTED: "accepted_at",
    RequestStatus.DONE: "done_at",
    RequestStatus.ACCEPTED_BY_USER: "accepted_by_user_at",
    RequestStatus.PAID: "paid_at",
}

# Тип субъекта → автор сообщения (§6.2). Агент действует как ИИ.
_AUTHOR_BY_KIND: dict[PrincipalKind, AuthorType] = {
    PrincipalKind.REQUESTER: AuthorType.REQUESTER,
    PrincipalKind.OPERATOR: AuthorType.OPERATOR,
    PrincipalKind.PARTNER: AuthorType.PARTNER,
    PrincipalKind.AGENT: AuthorType.AI,
    PrincipalKind.SERVICE: AuthorType.SYSTEM,
}

# Потолок размера страницы списка (§11 курсорная пагинация; анти-абьюз NFR-11).
_MAX_PAGE_LIMIT = 100
_DEFAULT_PAGE_LIMIT = 50


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


class RequestService:
    """Чтение и жизненный цикл заявок (M1.3): карточка, список, переходы FSM,
    сообщения/заметки, отмена.

    Видимость (контур + владение) проверяется ПЕРЕД авторизацией действия: невидимый
    ресурс → 404, видимый-но-без-прав → 403 (анти-enumeration, §12).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = RequestRepository(session)

    async def get_detail(self, principal: Principal, request_id: uuid.UUID) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id)
        if request is None:
            raise ProblemException.not_found()
        return self._to_detail(principal, request)

    async def list_requests(
        self,
        principal: Principal,
        filters: RequestListFilters,
        *,
        cursor: str | None,
        limit: int | None,
    ) -> RequestListResponse:
        page_limit = min(limit or _DEFAULT_PAGE_LIMIT, _MAX_PAGE_LIMIT)
        decoded = decode_cursor(cursor) if cursor else None
        rows = await self._repo.list_visible(principal, filters, cursor=decoded, limit=page_limit)
        has_more = len(rows) > page_limit
        items = rows[:page_limit]
        next_cursor = (
            encode_cursor(items[-1].created_at, items[-1].id) if has_more and items else None
        )
        return RequestListResponse(
            items=[RequestRead.model_validate(r) for r in items],
            next_cursor=next_cursor,
        )

    async def transition(
        self, principal: Principal, request_id: uuid.UUID, body: TransitionRequest
    ) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not can_drive_lifecycle(principal):
            raise ProblemException.forbidden(detail="Lifecycle transition not allowed for subject")
        self._apply_transition(principal, request, body.target)
        # Карточку строим ДО commit: объект, загруженный с FOR UPDATE, после commit
        # экспайрится (блокировка снята → данные потенциально устарели), и ленивое
        # дочитывание в async-контексте упало бы.
        detail = self._to_detail(principal, request)
        await self._session.commit()
        return detail

    async def cancel(
        self, principal: Principal, request_id: uuid.UUID, reason: str
    ) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        if not can_cancel(principal):
            raise ProblemException.forbidden(detail="Cancellation not allowed for subject")
        self._apply_transition(principal, request, RequestStatus.CANCELLED)
        request.custom_fields = {**request.custom_fields, "cancellation": {"reason": reason}}
        detail = self._to_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        return detail

    async def add_message(
        self, principal: Principal, request_id: uuid.UUID, body: MessageCreate
    ) -> MessageRead:
        request = await self._repo.get_visible(principal, request_id)
        if request is None:
            raise ProblemException.not_found()
        if body.is_internal and not can_view_internal(principal):
            raise ProblemException.forbidden(detail="Internal notes are operator-only")
        message = RequestMessage(
            request_id=request.id,
            author_type=_AUTHOR_BY_KIND[principal.kind],
            author_id=str(principal.user_id),
            is_internal=body.is_internal,
            text=body.text,
            attachments=[a.model_dump() for a in body.attachments],
        )
        self._repo.add_message(message)
        await self._session.flush()
        self._session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=principal.on_behalf_of or principal.user_id,
                action=HistoryAction.MESSAGE_ADDED,
                to_value=str(message.id),
            )
        )
        await self._session.commit()
        return MessageRead.model_validate(message)

    async def list_messages(self, principal: Principal, request_id: uuid.UUID) -> list[MessageRead]:
        request = await self._repo.get_visible(principal, request_id)
        if request is None:
            raise ProblemException.not_found()
        messages = await self._repo.list_messages(
            request.id, include_internal=can_view_internal(principal)
        )
        return [MessageRead.model_validate(m) for m in messages]

    def _apply_transition(
        self, principal: Principal, request: ServiceRequest, target: RequestStatus
    ) -> None:
        """Сменить статус с валидацией FSM (§7, запрещённый → 409) и записью аудита."""
        previous = request.status
        ensure_transition(previous, target)
        request.status = target
        timestamp_field = _STATUS_TIMESTAMP.get(target)
        if timestamp_field is not None:
            setattr(request, timestamp_field, datetime.datetime.now(datetime.UTC))
        self._session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=principal.on_behalf_of or principal.user_id,
                action=HistoryAction.STATUS_CHANGED,
                from_value=previous.value,
                to_value=target.value,
            )
        )

    @staticmethod
    def _to_detail(principal: Principal, request: ServiceRequest) -> RequestDetail:
        raw = (
            request.raw_input if can_see_raw_input(principal, request) else request.raw_input_masked
        )
        return RequestDetail(
            id=request.id,
            number=request.number,
            requester_id=request.requester_id,
            channel_in=request.channel_in,
            category=request.category,
            status=request.status,
            created_at=request.created_at,
            partner_id=request.partner_id,
            product_code=request.product_code,
            booking_id=request.booking_id,
            premises_id=request.premises_id,
            updated_at=request.updated_at,
            raw_input=raw,
            allowed_transitions=sorted(allowed_transitions(request.status), key=lambda s: s.value),
        )
