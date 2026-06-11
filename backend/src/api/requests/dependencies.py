"""FastAPI-зависимости домена заявок: RBAC и фабрика сервиса приёма.

`require_service_principal` — гейт для `from-chat`/`from-ticket` (только m2m,
acceptance E1). `get_intake_service` — точка инъекции `IntakeService` (тесты
переопределяют её через `app.dependency_overrides`).
"""

from __future__ import annotations

import datetime

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.db import get_session
from api.errors import ProblemException
from api.requests.enums import Category, RequestStatus
from api.requests.repository import RequestListFilters
from api.requests.service import IntakeService, RequestService


async def require_service_principal(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Требовать сервис-принципал (m2m). Иначе 403 (FR-1.2/FR-1.3, acceptance E1)."""
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(detail="Service principal required")
    return principal


def get_intake_service(session: AsyncSession = Depends(get_session)) -> IntakeService:
    """Сервис приёма заявок на сессию запроса."""
    return IntakeService(session)


def get_request_service(session: AsyncSession = Depends(get_session)) -> RequestService:
    """Сервис чтения/жизненного цикла заявок на сессию запроса."""
    return RequestService(session)


def get_list_filters(
    status: RequestStatus | None = Query(default=None),
    category: Category | None = Query(default=None),
    partner_id: str | None = Query(default=None, max_length=255),
    created_from: datetime.datetime | None = Query(default=None),
    created_to: datetime.datetime | None = Query(default=None),
) -> RequestListFilters:
    """Фильтры списка заявок из query-параметров (§11.1)."""
    return RequestListFilters(
        status=status,
        category=category,
        partner_id=partner_id,
        created_from=created_from,
        created_to=created_to,
    )
