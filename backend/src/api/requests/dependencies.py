"""FastAPI-зависимости домена заявок: RBAC и фабрика сервиса приёма.

`require_service_principal` — гейт для `from-chat`/`from-ticket` (только m2m,
acceptance E1). `get_intake_service` — точка инъекции `IntakeService` (тесты
переопределяют её через `app.dependency_overrides`).
"""

from __future__ import annotations

import datetime
import time
from collections.abc import AsyncIterator

import httpx
from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.classifier.engine import ClassifierEngine
from api.classifier.provider import build_llm_provider
from api.clients.auth import StaticTokenProvider
from api.clients.cache import InMemoryCache
from api.clients.factory import build_resilient_client
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.support.adapter import HttpKbSupportClient
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException
from api.matching.engine import Matcher
from api.requests.acceptance import AcceptanceService
from api.requests.enums import Category, RequestStatus
from api.requests.repository import RequestListFilters
from api.requests.service import (
    AssignmentService,
    ClassificationService,
    IntakeService,
    RequestService,
)

# Кеш реестра партнёров — процесс-синглтон (справочные read-only данные переживают
# запросы). HTTP-клиент/breaker — per-request (жизненный цикл httpx у вызывающего,
# как в эталоне kb-support); персистентный app-level breaker — будущая оптимизация.
_PLATFORM_CACHE = InMemoryCache(now=time.monotonic)


async def require_service_principal(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Требовать сервис-принципал (m2m). Иначе 403 (FR-1.2/FR-1.3, acceptance E1)."""
    if principal.kind is not PrincipalKind.SERVICE:
        raise ProblemException.forbidden(detail="Service principal required")
    return principal


def get_intake_service(session: AsyncSession = Depends(get_session)) -> IntakeService:
    """Сервис приёма заявок на сессию запроса (с гейтом авто-пайплайна)."""
    return IntakeService(session, automation_on_create=get_settings().automation_on_create_enabled)


def get_request_service(session: AsyncSession = Depends(get_session)) -> RequestService:
    """Сервис чтения/жизненного цикла заявок на сессию запроса."""
    return RequestService(session)


def get_classification_service(
    session: AsyncSession = Depends(get_session),
) -> ClassificationService:
    """Сервис классификации (E2): движок rules+LLM из конфигурации (env-switch)."""
    settings = get_settings()
    engine = ClassifierEngine(build_llm_provider(settings.classifier_llm_provider))
    return ClassificationService(session, engine, settings.classifier_confidence_threshold)


async def get_assignment_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[AssignmentService]:
    """Сервис подбора/назначения (E3): platform-клиент реестра + matcher.

    Открывает httpx-клиент к kb-platform на время запроса (закрывается по выходу).
    """
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.platform_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        platform = HttpPlatformClient(
            http_client=build_resilient_client("platform", http, settings),
            token_provider=StaticTokenProvider(settings.platform_api_token),
            cache=_PLATFORM_CACHE,
            cache_ttl_seconds=settings.platform_cache_ttl_seconds,
        )
        yield AssignmentService(
            session,
            platform,
            Matcher(),
            require_service_order=bool(settings.platform_api_token),
        )


async def get_acceptance_service(
    session: AsyncSession = Depends(get_session),
) -> AsyncIterator[AcceptanceService]:
    """Сервис приёмки/спора (E7): клиент kb-support (claims), config-gated."""
    settings = get_settings()
    async with httpx.AsyncClient(
        base_url=settings.kb_support_api_base_url, timeout=settings.client_timeout_seconds
    ) as http:
        support = HttpKbSupportClient(
            http_client=build_resilient_client("kb_support", http, settings),
            token_provider=StaticTokenProvider(settings.kb_support_api_token),
        )
        yield AcceptanceService(session, support, enable_claims=bool(settings.kb_support_api_token))


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
