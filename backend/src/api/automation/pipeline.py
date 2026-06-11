"""On_create-пайплайн автоматизации (FR-6.3): классификация→подбор→диспетчеризация.

Выполняется ВОРКЕРОМ по outbox-задаче `automation_on_create` под СИСТЕМНЫМ субъектом
с правами оператора (иначе не пройдёт `get_visible`/`can_drive_lifecycle`). Действия
атрибутируются `AUTOMATION_ACTOR_ID` в истории.

Пайплайн идемпотентно-перезапускаем: каждый шаг толерантен к 409 (этап уже пройден
при повторе после visibility-timeout). Ветки human-handoff (NEEDS_REVIEW при низкой
уверенности; нет пригодного партнёра) останавливают пайплайн без ошибки — заявку
дальше ведёт оператор (FR-9.4).
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.scopes import STAFF_ADMIN_SCOPE
from api.auth.system_actors import AUTOMATION_ACTOR_ID
from api.channels.dispatch import DispatchService
from api.channels.resolver import ChannelResolver
from api.classifier.engine import ClassifierEngine
from api.clients.platform.protocol import PlatformClient
from api.config import Settings
from api.errors import ProblemException
from api.matching.engine import Matcher
from api.observability.logging import get_logger
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus
from api.requests.schemas import AssignRequest
from api.requests.service import AssignmentService, ClassificationService
from api.sla.engine import SlaPolicy

_logger = get_logger("automation")

ON_CREATE_KIND = "automation_on_create"

# Системный субъект автоматизации: оператор + admin-скоуп → видит/двигает любую заявку.
AUTOMATION_PRINCIPAL = Principal(
    user_id=AUTOMATION_ACTOR_ID,
    kind=PrincipalKind.OPERATOR,
    scopes=frozenset({STAFF_ADMIN_SCOPE}),
)


@dataclass(frozen=True)
class AutomationDeps:
    """Зависимости пайплайна (строит воркер из конфигурации)."""

    engine: ClassifierEngine
    confidence_threshold: float
    platform: PlatformClient
    matcher: Matcher
    resolver: ChannelResolver
    policy: SlaPolicy
    require_service_order: bool


async def run_on_create(session: AsyncSession, request_id: uuid.UUID, deps: AutomationDeps) -> str:
    """Прогнать заявку по пайплайну. Возвращает исход для логов/метрик."""
    principal = AUTOMATION_PRINCIPAL

    classify = ClassificationService(session, deps.engine, deps.confidence_threshold)
    try:
        detail = await classify.classify(principal, request_id)
        if detail.status is RequestStatus.NEEDS_REVIEW:
            return "needs_review"  # низкая уверенность → human-handoff
    except ProblemException as exc:
        if exc.status != 409:  # 409 — уже классифицирована (повтор); прочее пробрасываем
            raise

    assign = AssignmentService(
        session, deps.platform, deps.matcher, require_service_order=deps.require_service_order
    )
    try:
        await assign.assign(principal, request_id, AssignRequest())
    except ProblemException as exc:
        if exc.status == 422:
            return "no_partner"  # нет пригодного партнёра → human-handoff
        if exc.status != 409:
            raise

    dispatch = DispatchService(session, deps.resolver, deps.policy)
    try:
        await dispatch.dispatch(principal, request_id)
    except ProblemException as exc:
        if exc.status != 409:
            raise

    return "dispatched"


async def drain_on_create_batch(
    session: AsyncSession, deps: AutomationDeps, *, settings: Settings
) -> int:
    """Воркерный дрейн пачки `automation_on_create`. Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(
        kind=ON_CREATE_KIND,
        now=now,
        limit=settings.outbox_batch_size,
        visibility_timeout=settings.outbox_visibility_timeout_seconds,
    )
    for message in batch:
        try:
            request_id = uuid.UUID(str(message.payload["request_id"]))
            outcome = await run_on_create(session, request_id, deps)
            repo.mark_done(message, now)
            _logger.info("automation on_create: request=%s outcome=%s", request_id, outcome)
        except Exception as exc:  # noqa: BLE001 — инфраошибка → backoff-повтор
            delay = settings.outbox_retry_base_seconds * (2 ** (message.attempts - 1))
            repo.mark_failed_or_retry(
                message,
                error=f"{type(exc).__name__}: {exc}",
                now=now,
                max_attempts=settings.outbox_max_attempts,
                retry_at=now + datetime.timedelta(seconds=delay),
            )
    await session.commit()
    return len(batch)
