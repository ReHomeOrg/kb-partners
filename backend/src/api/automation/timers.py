"""Time_based-движок автоматизации (E6, FR-4.4/4.5/5.3/6.3): авто-fallback по SLA.

Воркерный скан DISPATCHED-заявок с breach дедлайна принятия (`accept_deadline`):
партнёр не принял заявку в срок → возврат в MATCHING и переход к СЛЕДУЮЩЕМУ партнёру
из `fallback_chain` (FR-5.3); исчерпание цепочки → FAILED_DISPATCH + эскалация
оператору (FR-4.5). Дедлайны/breach считаются тем же `SlaPolicy`, что и на чтении
(FR-6.2) — воркер лишь ДЕЙСТВУЕТ по ним. Config-gated (`automation_time_based_enabled`).

Действия атрибутируются системному `SLA_ACTOR_ID` в `RequestHistory`.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import SLA_ACTOR_ID
from api.channels.dispatch import execute_dispatch
from api.channels.resolver import ChannelResolver
from api.config import Settings
from api.notifications.emitter import emit_operator_escalation
from api.observability.logging import get_logger
from api.outbox.models import OutboxMessage
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus
from api.requests.models import ServiceRequest
from api.requests.repository import RequestRepository
from api.requests.service import apply_transition
from api.sla.engine import SlaPolicy, SlaState

_logger = get_logger("automation.timers")

# Системный субъект таймеров SLA (breach/эскалации) для атрибуции в истории.
SLA_TIMER_PRINCIPAL = Principal(user_id=SLA_ACTOR_ID, kind=PrincipalKind.SERVICE)

# Outbox-вид: авто-fallback после ОТКЛОНЕНИЯ партнёром (FR-5.3). Ставится при переходе
# заявки в MATCHING по статусу партнёра «rejected»; дрейнится тем же redispatch_to_next.
PARTNER_FALLBACK_KIND = "partner_fallback"


def _next_partner(request: ServiceRequest) -> str | None:
    """Снять следующего партнёра с головы `fallback_chain` (мутирует заявку).

    Сдвиг сохраняет остаток цепочки для последующих fallback-итераций. Возвращает
    None, если цепочка пуста (партнёров больше нет).
    """
    chain = list(request.fallback_chain or [])
    if not chain:
        return None
    nxt, *rest = chain
    request.partner_id = nxt
    request.fallback_chain = rest
    return nxt


async def redispatch_to_next(
    session: AsyncSession,
    request: ServiceRequest,
    *,
    resolver: ChannelResolver,
    policy: SlaPolicy,
) -> str:
    """Переназначить MATCHING-заявку на следующего партнёра цепочки и передиспетчеризовать.

    Предусловие: `request.status is MATCHING`. Нет следующего партнёра → эскалация
    оператору, заявка остаётся в MATCHING (human-handoff; ребра MATCHING→FAILED_DISPATCH
    в §7 нет). Иначе MATCHING→ASSIGNED→DISPATCHED + доставка (`execute_dispatch` сам
    переведёт в FAILED_DISPATCH при провале доставки всей оставшейся цепочки).
    """
    if _next_partner(request) is None:
        emit_operator_escalation(
            session,
            request_id=request.id,
            number=request.number,
            status=request.status,
            summary="Fallback-цепочка исчерпана — требуется оператор",
        )
        _logger.info("fallback exhausted (no next partner): number=%s", request.number)
        return "exhausted"
    apply_transition(session, SLA_TIMER_PRINCIPAL, request, RequestStatus.ASSIGNED)
    apply_transition(session, SLA_TIMER_PRINCIPAL, request, RequestStatus.DISPATCHED)
    delivered = await execute_dispatch(session, request, resolver=resolver, policy=policy)
    _logger.info("fallback redispatched: number=%s delivered=%s", request.number, delivered)
    return "redispatched" if delivered else "failed_dispatch"


async def run_accept_timeout_fallback(
    session: AsyncSession,
    request: ServiceRequest,
    *,
    resolver: ChannelResolver,
    policy: SlaPolicy,
) -> str:
    """Откатить просроченную (accept breach) DISPATCHED-заявку (FR-4.4/4.5).

    Нет fallback-цепочки → DISPATCHED→FAILED_DISPATCH (решаем, пока ещё в DISPATCHED —
    единственный легальный путь к FAILED_DISPATCH, §7) + авто-эскалация (уведомление
    на FAILED_DISPATCH). Иначе DISPATCHED→MATCHING и `redispatch_to_next`.
    """
    if not request.fallback_chain:
        apply_transition(session, SLA_TIMER_PRINCIPAL, request, RequestStatus.FAILED_DISPATCH)
        _logger.info("accept timeout, chain empty → FAILED_DISPATCH: number=%s", request.number)
        return "failed_dispatch"
    apply_transition(session, SLA_TIMER_PRINCIPAL, request, RequestStatus.MATCHING)
    return await redispatch_to_next(session, request, resolver=resolver, policy=policy)


async def scan_accept_timeouts(
    session: AsyncSession,
    *,
    resolver: ChannelResolver,
    policy: SlaPolicy,
    settings: Settings,
    now: datetime.datetime | None = None,
) -> int:
    """Просканировать DISPATCHED-заявки с breach принятия и откатить на fallback.

    Инертно при выключенном `automation_time_based_enabled`. Грубый пред-фильтр по
    сырому дедлайну в SQL, точный breach подтверждается `SlaPolicy.evaluate` (учёт
    пауз). Возвращает число фактически откаченных заявок.
    """
    if not settings.automation_time_based_enabled:
        return 0
    moment = now or datetime.datetime.now(datetime.UTC)
    repo = RequestRepository(session)
    candidates = await repo.list_accept_overdue(moment, limit=settings.outbox_batch_size)
    processed = 0
    with session.no_autoflush:
        for request in candidates:
            state = policy.evaluate(request.sla, deadline_key="accept_deadline", now=moment)
            if state is not SlaState.BREACHED:
                continue
            await run_accept_timeout_fallback(session, request, resolver=resolver, policy=policy)
            processed += 1
    await session.commit()
    _logger.info("sla accept-timeout scan: candidates=%d processed=%d", len(candidates), processed)
    return processed


async def _load_for_update(session: AsyncSession, request_id: uuid.UUID) -> ServiceRequest | None:
    stmt = select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _process_partner_fallback(
    session: AsyncSession,
    message: OutboxMessage,
    *,
    resolver: ChannelResolver,
    policy: SlaPolicy,
) -> None:
    """Откатить отклонённую партнёром заявку на следующего (один outbox-message).

    Заявка уже в MATCHING (перевёл `advance_partner_status`). Если статус уже иной
    (оператор/агент успел переназначить) — no-op (идемпотентно).
    """
    raw_id = message.payload.get("request_id")
    request = await _load_for_update(session, uuid.UUID(str(raw_id))) if raw_id else None
    if request is None or request.status is not RequestStatus.MATCHING:
        return
    with session.no_autoflush:
        await redispatch_to_next(session, request, resolver=resolver, policy=policy)


async def drain_partner_fallback_batch(
    session: AsyncSession, *, resolver: ChannelResolver, policy: SlaPolicy, settings: Settings
) -> int:
    """Воркерный дрейн `partner_fallback` (FR-5.3). Возвращает число обработанных."""
    repo = OutboxRepository(session)
    now = datetime.datetime.now(datetime.UTC)
    batch = await repo.claim_batch(
        kind=PARTNER_FALLBACK_KIND,
        now=now,
        limit=settings.outbox_batch_size,
        visibility_timeout=settings.outbox_visibility_timeout_seconds,
    )
    for message in batch:
        try:
            await _process_partner_fallback(session, message, resolver=resolver, policy=policy)
            repo.mark_done(message, now)
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
