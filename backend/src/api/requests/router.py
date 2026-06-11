"""HTTP-роутер заявок (§11.1). Префикс монтируется в main: `/api/v1/partners`.

M1.2 — приём (E1): `POST /requests`, `/requests/from-chat`, `/requests/from-ticket`.
Read / transition / messages — M1.3.

Идемпотентность: повторная доставка возвращает существующую заявку с кодом 200
(а не 201) и не создаёт дубль (acceptance E1).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Response, status

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.requests.dependencies import get_intake_service, require_service_principal
from api.requests.schemas import FromChatCreate, FromTicketCreate, RequestCreate, RequestRead
from api.requests.service import IntakeService

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
