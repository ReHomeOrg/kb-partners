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
from api.classifier.engine import ClassifierEngine
from api.clients.platform.protocol import PlatformClient
from api.config import get_settings
from api.errors import ProblemException
from api.matching.engine import Matcher
from api.notifications.emitter import emit_notifications
from api.observability.logging import get_logger
from api.observability.pii_mask import mask_pii
from api.outbox.repository import OutboxRepository
from api.requests.access import (
    can_cancel,
    can_drive_lifecycle,
    can_see_raw_input,
    can_view_internal,
)
from api.requests.enums import (
    AccessLevel,
    AuthorType,
    Category,
    ChannelIn,
    HistoryAction,
    RequestStatus,
)
from api.requests.fsm import allowed_transitions, ensure_transition
from api.requests.metrics import record_transition
from api.requests.models import RequestHistory, RequestMessage, ServiceRequest
from api.requests.pagination import decode_cursor, encode_cursor
from api.requests.repository import RequestListFilters, RequestRepository
from api.requests.schemas import (
    AssignRequest,
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
from api.sla.engine import SlaPolicy, sla_view
from api.webhooks.emitter import emit_event, status_event

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


def apply_transition(
    session: AsyncSession, principal: Principal, request: ServiceRequest, target: RequestStatus
) -> None:
    """Сменить статус с валидацией FSM (§7, запрещённый → 409) и записью аудита.

    Общий хелпер для жизненного цикла (transition/cancel) и классификации (E2).
    Commit — у вызывающего сервиса.
    """
    previous = request.status
    ensure_transition(previous, target)
    transitioned_at = datetime.datetime.now(datetime.UTC)
    request.status = target
    timestamp_field = _STATUS_TIMESTAMP.get(target)
    if timestamp_field is not None:
        setattr(request, timestamp_field, transitioned_at)
    session.add(
        RequestHistory(
            request_id=request.id,
            actor_id=principal.on_behalf_of or principal.user_id,
            action=HistoryAction.STATUS_CHANGED,
            from_value=previous.value,
            to_value=target.value,
        )
    )
    record_transition(
        target=target,
        at=transitioned_at,
        created_at=request.created_at,
        dispatched_at=request.dispatched_at,
        accepted_at=request.accepted_at,
    )
    # Доменное событие в outbox (доставка после commit, E8) — если webhooks включены.
    emit_event(
        session,
        event=status_event(target),
        request_id=request.id,
        number=request.number,
        status=target,
    )
    # Уведомления заявителю/партнёру/оператору (E8, FR-8.1/8.2) — если включены.
    emit_notifications(session, request_id=request.id, number=request.number, status=target)


def build_detail(principal: Principal, request: ServiceRequest) -> RequestDetail:
    """Собрать карточку заявки с masking `raw_input` по scope (§11.1, FR-4.6).

    Строится из загруженного объекта — вызывать ДО commit для сущностей, прочитанных
    с FOR UPDATE (после commit они экспайрятся, ленивое дочитывание упадёт в async).
    """
    raw = request.raw_input if can_see_raw_input(principal, request) else request.raw_input_masked
    # Объяснимость подбора раскрывает id конкурентов-партнёров — только сотрудникам.
    staff_view = can_view_internal(principal)
    sla = sla_view(
        request.sla,
        accepted_at=request.accepted_at,
        done_at=request.done_at,
        policy=SlaPolicy.from_settings(get_settings()),
        now=datetime.datetime.now(datetime.UTC),
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
        delivery_channel=request.delivery_channel,
        service_order_id=request.service_order_id,
        amount_ref=request.amount_ref,
        escrow_ref=request.escrow_ref,
        dispute_id=request.dispute_id,
        claim_ref=request.claim_ref,
        updated_at=request.updated_at,
        raw_input=raw,
        classification=request.classification,
        sla=sla,
        match_trace=request.match_trace if staff_view else None,
        fallback_chain=request.fallback_chain if staff_view else None,
        allowed_transitions=sorted(allowed_transitions(request.status), key=lambda s: s.value),
    )


class IntakeService:
    """Создание заявок из каналов приёма E1. Возвращает `(заявка, создана?)`."""

    def __init__(self, session: AsyncSession, *, automation_on_create: bool = False) -> None:
        self._session = session
        self._repo = RequestRepository(session)
        self._automation_on_create = automation_on_create

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
        if self._automation_on_create:
            # Атомарно с созданием заявки ставим задачу авто-пайплайна (E6, FR-6.3).
            OutboxRepository(self._session).enqueue(
                "automation_on_create", {"request_id": str(request.id)}
            )
        emit_event(
            self._session,
            event="request.created",
            request_id=request.id,
            number=request.number,
            status=RequestStatus.NEW,
        )
        # FR-8.1: уведомить заявителя «заявка принята» (NEW создаётся не через
        # apply_transition, поэтому эмитим явно). Инертно, пока уведомления выключены.
        emit_notifications(
            self._session,
            request_id=request.id,
            number=request.number,
            status=RequestStatus.NEW,
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
        return build_detail(principal, request)

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
        apply_transition(self._session, principal, request, body.target)
        # Карточку строим ДО commit: объект, загруженный с FOR UPDATE, после commit
        # экспайрится (блокировка снята → данные потенциально устарели), и ленивое
        # дочитывание в async-контексте упало бы.
        detail = build_detail(principal, request)
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
        apply_transition(self._session, principal, request, RequestStatus.CANCELLED)
        request.custom_fields = {**request.custom_fields, "cancellation": {"reason": reason}}
        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
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


# Статусы, из которых допустима (ре)классификация (E2). NEW — первичная;
# CLASSIFIED/NEEDS_REVIEW — реклассификация по запросу оператора/агента (FR-2.5).
_CLASSIFIABLE_STATUSES = frozenset(
    {RequestStatus.NEW, RequestStatus.CLASSIFIED, RequestStatus.NEEDS_REVIEW}
)


class ClassificationService:
    """Классификация категории заявки (E2): rules+LLM, порог → NEEDS_REVIEW, аудит.

    На вход движку идёт только `raw_input_masked` (FR-1.6). Решение и его
    трассировка пишутся в `classification` и `RequestHistory` (FR-2.6).
    """

    def __init__(
        self, session: AsyncSession, engine: ClassifierEngine, confidence_threshold: float
    ) -> None:
        self._session = session
        self._repo = RequestRepository(session)
        self._engine = engine
        self._threshold = confidence_threshold

    async def classify(self, principal: Principal, request_id: uuid.UUID) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        # Классификация/реклассификация — оператор или агент (FR-2.5).
        if not can_drive_lifecycle(principal):
            raise ProblemException.forbidden(detail="Classification not allowed for subject")
        if request.status not in _CLASSIFIABLE_STATUSES:
            raise ProblemException.conflict(
                detail=f"Classification not allowed in status {request.status.value}"
            )

        outcome = await self._engine.classify(request.raw_input_masked)
        classified_at = datetime.datetime.now(datetime.UTC)
        request.category = outcome.category
        request.product_code = outcome.product_code
        request.classification = outcome.to_classification(classified_at)
        confident = outcome.confidence >= self._threshold and outcome.category is not Category.OTHER

        self._route_status(principal, request, confident=confident)
        self._session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=principal.on_behalf_of or principal.user_id,
                action=HistoryAction.CLASSIFIED,
                from_value=outcome.method,
                to_value=outcome.category.value,
            )
        )
        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        _logger.info(
            "request classified: number=%s category=%s method=%s confident=%s",
            request.number,
            outcome.category.value,
            outcome.method,
            confident,
        )
        return detail

    def _route_status(
        self, principal: Principal, request: ServiceRequest, *, confident: bool
    ) -> None:
        """Провести FSM по итогу классификации (§7).

        Первичная (NEW): NEW→CLASSIFYING→CLASSIFIED, при низкой уверенности далее
        CLASSIFIED→NEEDS_REVIEW. Реклассификация: из CLASSIFIED при падении уверенности
        → NEEDS_REVIEW; из NEEDS_REVIEW статус не меняется (нет легального ребра к
        CLASSIFIED по §7) — обновляются только метаданные, дальше оператор назначает.
        """
        if request.status is RequestStatus.NEW:
            apply_transition(self._session, principal, request, RequestStatus.CLASSIFYING)
            apply_transition(self._session, principal, request, RequestStatus.CLASSIFIED)
        if not confident and request.status is RequestStatus.CLASSIFIED:
            apply_transition(self._session, principal, request, RequestStatus.NEEDS_REVIEW)


# Статусы, из которых допустимо назначение/переназначение (E3). Каждый имеет в §7
# ребро в MATCHING (или уже MATCHING) → далее MATCHING→ASSIGNED.
_ASSIGNABLE_STATUSES = frozenset(
    {
        RequestStatus.CLASSIFIED,
        RequestStatus.NEEDS_REVIEW,
        RequestStatus.MATCHING,
        RequestStatus.DISPATCHED,
        RequestStatus.FAILED_DISPATCH,
    }
)


class AssignmentService:
    """Подбор и назначение партнёра (E3): авто-ранжирование или ручное назначение.

    Авто-режим тянет кандидатов из реестра kb-platform (по HTTP, арх-константа),
    ранжирует (`Matcher`), пишет `partner_id`/`delivery_channel`/`fallback_chain`/
    `match_trace`, создаёт/привязывает `ServiceOrder` в kb-platform (FR-3.5,
    идемпотентно по ключу заявки, ADR-0002) и ведёт FSM …→MATCHING→ASSIGNED.

    `require_service_order=False` (платёжный/реестровый контур не сконфигурирован,
    dev) → оркестрация заказа пропускается (инертна, как прочие интеграции).
    """

    def __init__(
        self,
        session: AsyncSession,
        platform: PlatformClient,
        matcher: Matcher,
        *,
        require_service_order: bool = False,
    ) -> None:
        self._session = session
        self._repo = RequestRepository(session)
        self._platform = platform
        self._matcher = matcher
        self._require_service_order = require_service_order

    async def assign(
        self, principal: Principal, request_id: uuid.UUID, body: AssignRequest
    ) -> RequestDetail:
        request = await self._repo.get_visible(principal, request_id, for_update=True)
        if request is None:
            raise ProblemException.not_found()
        # Назначение/переназначение — оператор или агент (FR-3.4).
        if not can_drive_lifecycle(principal):
            raise ProblemException.forbidden(detail="Assignment not allowed for subject")
        if request.status not in _ASSIGNABLE_STATUSES:
            raise ProblemException.conflict(
                detail=f"Assignment not allowed in status {request.status.value}"
            )
        # ServiceOrder в kb-platform категоризован — без категории заказ не создать.
        if request.category is None:
            raise ProblemException.conflict(detail="Request must be classified before assignment")
        category = request.category  # narrowed → Category

        if body.partner_id is not None:
            self._apply_manual(request, body.partner_id)
        else:
            await self._apply_auto(request, category, body.service_area)

        await self._orchestrate_service_order(request, category)
        self._route_to_assigned(principal, request)
        self._session.add(
            RequestHistory(
                request_id=request.id,
                actor_id=principal.on_behalf_of or principal.user_id,
                action=HistoryAction.ASSIGNED,
                from_value="manual" if body.partner_id is not None else "auto",
                to_value=request.partner_id,
            )
        )
        detail = build_detail(principal, request)  # до commit (FOR UPDATE экспайрит)
        await self._session.commit()
        _logger.info(
            "request assigned: number=%s partner=%s channel=%s",
            request.number,
            request.partner_id,
            request.delivery_channel,
        )
        return detail

    def _apply_manual(self, request: ServiceRequest, partner_id: str) -> None:
        """Ручное назначение: партнёр задан оператором/агентом (FR-3.4)."""
        request.partner_id = partner_id
        request.delivery_channel = None  # канал определит диспетчеризация (E4) из конфига
        request.fallback_chain = []
        request.match_trace = {"method": "manual", "partner_id": partner_id}

    async def _apply_auto(
        self, request: ServiceRequest, category: Category, service_area: str | None
    ) -> None:
        """Авто-подбор: кандидаты из реестра → ранжирование → запись результата."""
        candidates = await self._platform.search_candidates(
            category=category.value, service_area=service_area
        )
        result = self._matcher.rank(candidates, category=category.value, service_area=service_area)
        if result is None:
            # Нет пригодных партнёров — назначить нечего (human-handoff остаётся оператору).
            raise ProblemException.unprocessable(detail="No eligible partner found")
        request.partner_id = result.partner_id
        request.delivery_channel = result.delivery_channel
        request.fallback_chain = result.fallback_chain
        request.match_trace = {
            **result.match_trace,
            "matched_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }

    async def _orchestrate_service_order(self, request: ServiceRequest, category: Category) -> None:
        """Создать/привязать ServiceOrder в kb-platform (FR-3.5, идемпотентно по заявке).

        Инертно, если контур не сконфигурирован (dev). При недоступности соседа —
        502: ничего не коммитим, повтор по тому же ключу не создаст дубль (ADR-0002).
        """
        if not self._require_service_order:
            return
        if request.partner_id is None:  # защита инварианта: партнёр уже выбран выше
            raise ProblemException.conflict(detail="Partner must be selected before ServiceOrder")
        ref = await self._platform.create_service_order(
            request_id=str(request.id),
            partner_id=request.partner_id,
            category=category.value,
            idempotency_key=f"assign:{request.id}",
        )
        if ref is None:
            raise ProblemException.bad_gateway(detail="ServiceOrder orchestration failed")
        request.service_order_id = ref.id

    def _route_to_assigned(self, principal: Principal, request: ServiceRequest) -> None:
        """Провести FSM в ASSIGNED через MATCHING (§7)."""
        if request.status is not RequestStatus.MATCHING:
            apply_transition(self._session, principal, request, RequestStatus.MATCHING)
        apply_transition(self._session, principal, request, RequestStatus.ASSIGNED)
