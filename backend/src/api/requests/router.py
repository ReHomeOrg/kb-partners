"""HTTP-роутер заявок (§11.1). Префикс монтируется в main: `/api/v1/partners`.

M1.2 — приём (E1): `POST /requests`, `/requests/from-chat`, `/requests/from-ticket`.
Read / transition / messages — M1.3.

Идемпотентность: повторная доставка возвращает существующую заявку с кодом 200
(а не 201) и не создаёт дубль (acceptance E1).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Response, status

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.channels.dependencies import get_dispatch_service
from api.channels.dispatch import DispatchService
from api.requests.acceptance import AcceptanceService
from api.requests.context import ContextService
from api.requests.dependencies import (
    get_acceptance_service,
    get_assignment_service,
    get_classification_service,
    get_context_service,
    get_intake_service,
    get_list_filters,
    get_partner_service,
    get_request_service,
    require_service_principal,
)
from api.requests.partner import PartnerService
from api.requests.repository import RequestListFilters
from api.requests.schemas import (
    AssignRequest,
    CancelRequest,
    DisputeRequest,
    FromChatCreate,
    FromTicketCreate,
    MessageCreate,
    MessageRead,
    PartnerResponse,
    RequestCreate,
    RequestDetail,
    RequesterContextResponse,
    RequestListResponse,
    RequestRead,
    SettlementConfirm,
    TransitionRequest,
)
from api.requests.service import (
    AssignmentService,
    ClassificationService,
    IntakeService,
    RequestService,
)

router = APIRouter(prefix="/requests", tags=["Requests"])

# Тело ответа при идемпотентном повторе — существующая заявка, статус 200.
_CREATE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"model": RequestRead, "description": "Идемпотентный повтор: существующая заявка."}
}


@router.post(
    "",
    response_model=RequestRead,
    status_code=status.HTTP_201_CREATED,
    responses=_CREATE_RESPONSES,
    summary="Приём заявки (ЛК-форма / m2m)",
)
async def create_request(
    body: RequestCreate,
    response: Response,
    principal: Principal = Depends(get_current_principal),
    service: IntakeService = Depends(get_intake_service),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RequestRead:
    """FR-1.1/FR-1.4. `channel_in` выводится из субъекта; `Idempotency-Key` дедуплит приём."""
    request, created = await service.create_from_form(principal, body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return RequestRead.model_validate(request)


@router.post(
    "/from-chat",
    response_model=RequestRead,
    status_code=status.HTTP_201_CREATED,
    responses=_CREATE_RESPONSES,
    summary="Приём заявки из AI-чата (kb-search, SERVICE-only)",
)
async def create_request_from_chat(
    body: FromChatCreate,
    response: Response,
    principal: Principal = Depends(require_service_principal),
    service: IntakeService = Depends(get_intake_service),
) -> RequestRead:
    """FR-1.2. Идемпотентность по `chat_session_id`; канал AI_CHAT."""
    request, created = await service.create_from_chat(principal, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return RequestRead.model_validate(request)


@router.post(
    "/from-ticket",
    response_model=RequestRead,
    status_code=status.HTTP_201_CREATED,
    responses=_CREATE_RESPONSES,
    summary="Эскалация заявки из тикета (kb-support, SERVICE-only)",
)
async def create_request_from_ticket(
    body: FromTicketCreate,
    response: Response,
    principal: Principal = Depends(require_service_principal),
    service: IntakeService = Depends(get_intake_service),
) -> RequestRead:
    """FR-1.3. Идемпотентность по `ticket_id`; канал SUPPORT_TICKET; обратная ссылка."""
    request, created = await service.create_from_ticket(principal, body)
    if not created:
        response.status_code = status.HTTP_200_OK
    return RequestRead.model_validate(request)


# --- Чтение и жизненный цикл (M1.3) ---------------------------------------


@router.get("", response_model=RequestListResponse, summary="Список заявок (scope-фильтр)")
async def list_requests(
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
    filters: RequestListFilters = Depends(get_list_filters),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> RequestListResponse:
    """Видимые субъекту заявки (контур + владение); курсорная пагинация, фильтры (§11.1)."""
    return await service.list_requests(principal, filters, cursor=cursor, limit=limit)


@router.get(
    "/{request_id}",
    response_model=RequestDetail,
    summary="Карточка заявки + allowed_transitions",
)
async def get_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
) -> RequestDetail:
    """Карточка с `allowed_transitions` (§7); masking `raw_input` по scope. Недоступная → 404."""
    return await service.get_detail(principal, request_id)


@router.post(
    "/{request_id}/transition",
    response_model=RequestDetail,
    summary="Переход статуса (валидация по FSM)",
)
async def transition_request(
    request_id: uuid.UUID,
    body: TransitionRequest,
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
) -> RequestDetail:
    """Переход FSM (§7): запрещённый → 409; невидимая → 404; нет прав → 403."""
    return await service.transition(principal, request_id, body)


@router.post(
    "/{request_id}/classify",
    response_model=RequestDetail,
    summary="(Ре)классификация категории (operator/agent)",
)
async def classify_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: ClassificationService = Depends(get_classification_service),
) -> RequestDetail:
    """E2: rules+LLM по `raw_input_masked`; ниже порога/неоднозначно → NEEDS_REVIEW (FR-2.4).

    Невидимая заявка → 404; нет прав (не operator/agent) → 403; недопустимый статус → 409.
    """
    return await service.classify(principal, request_id)


@router.post(
    "/{request_id}/assign",
    response_model=RequestDetail,
    summary="Подбор/назначение партнёра (operator/agent)",
)
async def assign_request(
    request_id: uuid.UUID,
    body: AssignRequest,
    principal: Principal = Depends(get_current_principal),
    service: AssignmentService = Depends(get_assignment_service),
) -> RequestDetail:
    """E3: `partner_id` → ручное назначение (FR-3.4); пусто → авто-подбор по реестру.

    Невидимая → 404; нет прав → 403; недопустимый статус → 409; нет кандидатов → 422.
    """
    return await service.assign(principal, request_id, body)


@router.post(
    "/{request_id}/dispatch",
    response_model=RequestDetail,
    summary="Диспетчеризация партнёру (operator/agent)",
)
async def dispatch_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: DispatchService = Depends(get_dispatch_service),
) -> RequestDetail:
    """E4: доставка по каналу с наивысшим priority; fallback по цепочке; исчерпание →
    FAILED_DISPATCH. Невидимая → 404; нет прав → 403; статус не ASSIGNED → 409."""
    return await service.dispatch(principal, request_id)


@router.post(
    "/{request_id}/accept",
    response_model=RequestDetail,
    summary="Приёмка пользователем",
)
async def accept_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: AcceptanceService = Depends(get_acceptance_service),
) -> RequestDetail:
    """FR-7.1: DONE→ACCEPTED_BY_USER. Партнёру недоступно (403); не DONE → 409; чужая → 404."""
    return await service.accept(principal, request_id)


@router.post(
    "/{request_id}/dispute",
    response_model=RequestDetail,
    summary="Открыть спор (с причиной)",
)
async def dispute_request(
    request_id: uuid.UUID,
    body: DisputeRequest,
    principal: Principal = Depends(get_current_principal),
    service: AcceptanceService = Depends(get_acceptance_service),
) -> RequestDetail:
    """FR-7.2: DONE|ACCEPTED_BY_USER→DISPUTE + претензия COMPENSATION в kb-support (claim_ref)."""
    return await service.dispute(principal, request_id, body.reason)


@router.post(
    "/{request_id}/settlement",
    response_model=RequestDetail,
    summary="Подтверждение расчёта контуром (SERVICE-only)",
)
async def confirm_settlement(
    request_id: uuid.UUID,
    body: SettlementConfirm,
    principal: Principal = Depends(require_service_principal),
    service: AcceptanceService = Depends(get_acceptance_service),
) -> RequestDetail:
    """FR-7.3: платёжный контур rehome.one подтверждает расчёт → ACCEPTED_BY_USER→PAID."""
    return await service.confirm_settlement(principal, request_id, body)


@router.post(
    "/{request_id}/cancel",
    response_model=RequestDetail,
    summary="Отмена заявки (с причиной)",
)
async def cancel_request(
    request_id: uuid.UUID,
    body: CancelRequest,
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
) -> RequestDetail:
    """Отмена из нетерминального статуса (§7); партнёру запрещена (403)."""
    return await service.cancel(principal, request_id, body.reason)


@router.post(
    "/{request_id}/partner-response",
    response_model=RequestDetail,
    summary="Ответ партнёра (портал LIGHT)",
)
async def partner_response(
    request_id: uuid.UUID,
    body: PartnerResponse,
    principal: Principal = Depends(get_current_principal),
    service: PartnerService = Depends(get_partner_service),
) -> RequestDetail:
    """E10/FR-10.2: партнёр accepted/rejected/in_progress/done по своей заявке.

    Только партнёр (403); чужая → 404; запрещённый переход → 409; неизвестный статус → 422.
    """
    return await service.respond(principal, request_id, body)


@router.get(
    "/{request_id}/requester-context",
    response_model=RequesterContextResponse,
    summary="Контекст заявителя из rehome.one (operator/agent)",
)
async def get_requester_context(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: ContextService = Depends(get_context_service),
) -> RequesterContextResponse:
    """E9/§11.1: User/Premises/Booking заявителя. Только оператор/агент (403); чужая → 404."""
    return await service.get_requester_context(principal, request_id)


@router.get(
    "/{request_id}/messages",
    response_model=list[MessageRead],
    summary="Сообщения заявки (внутренние — только операторам)",
)
async def list_messages(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
) -> list[MessageRead]:
    """Хронология сообщений; `is_internal`-заметки скрыты от заявителя/партнёра (правило 10)."""
    return await service.list_messages(principal, request_id)


@router.post(
    "/{request_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Сообщение/внутренняя заметка",
)
async def add_message(
    request_id: uuid.UUID,
    body: MessageCreate,
    principal: Principal = Depends(get_current_principal),
    service: RequestService = Depends(get_request_service),
) -> MessageRead:
    """Добавить сообщение; `is_internal=True` — только оператор (иначе 403). Невидимая → 404."""
    return await service.add_message(principal, request_id, body)
