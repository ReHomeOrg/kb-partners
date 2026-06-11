"""Машина состояний `ServiceRequest` (ТЗ §7).

Бэкенд — единственный источник истины по переходам: эндпоинт карточки отдаёт
`allowed_transitions`, фронт логику НЕ дублирует (CLAUDE.md §«Доменные ориентиры»).
Запрещённый переход → 409 (`ensure_transition`). Каждый совершённый переход
фиксируется записью в `RequestHistory` — это ответственность сервисного слоя (M1.3).

Диаграмма (§7):

    NEW → CLASSIFYING → CLASSIFIED → MATCHING → ASSIGNED → DISPATCHED → ACCEPTED
        → IN_PROGRESS → DONE → ACCEPTED_BY_USER → PAID
    ветвления:
        CLASSIFIED → NEEDS_REVIEW;  NEEDS_REVIEW → MATCHING
        DISPATCHED → MATCHING (отклонён/таймаут → следующий в fallback-цепочке)
        DISPATCHED → FAILED_DISPATCH (цепочка исчерпана);  FAILED_DISPATCH → MATCHING
        DONE | ACCEPTED_BY_USER → DISPUTE
        <любой нетерминальный> → CANCELLED

Терминальные: PAID, CANCELLED, REJECTED.
"""

from __future__ import annotations

from api.errors import ProblemException
from api.requests.enums import RequestStatus

_S = RequestStatus

#: Терминальные состояния — без исходящих переходов (§7).
TERMINAL_STATUSES: frozenset[RequestStatus] = frozenset({_S.PAID, _S.CANCELLED, _S.REJECTED})

# Базовые переходы строго по диаграмме §7. `CANCELLED` сюда НЕ включён — он
# добавляется ко всем нетерминальным статусам централизованно в `_build_allowed`
# (правило «<любой нетерминальный> → CANCELLED»), чтобы не дублировать его в каждой
# строке и не забыть при добавлении нового статуса.
_BASE_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = {
    _S.NEW: frozenset({_S.CLASSIFYING}),
    _S.CLASSIFYING: frozenset({_S.CLASSIFIED}),
    _S.CLASSIFIED: frozenset({_S.MATCHING, _S.NEEDS_REVIEW}),
    _S.NEEDS_REVIEW: frozenset({_S.MATCHING}),
    _S.MATCHING: frozenset({_S.ASSIGNED}),
    _S.ASSIGNED: frozenset({_S.DISPATCHED}),
    _S.DISPATCHED: frozenset({_S.ACCEPTED, _S.MATCHING, _S.FAILED_DISPATCH}),
    _S.FAILED_DISPATCH: frozenset({_S.MATCHING}),
    _S.ACCEPTED: frozenset({_S.IN_PROGRESS}),
    _S.IN_PROGRESS: frozenset({_S.DONE}),
    _S.DONE: frozenset({_S.ACCEPTED_BY_USER, _S.DISPUTE}),
    _S.ACCEPTED_BY_USER: frozenset({_S.PAID, _S.DISPUTE}),
    # Спор: претензия отклонена → закрытие заявки (`REJECTED`, §7). Разрешение спора
    # в пользу пользователя (возврат к ACCEPTED_BY_USER / PAID) уточняется в E7
    # (стыковка с COMPENSATION kb-support) — здесь не специфицируем заранее.
    _S.DISPUTE: frozenset({_S.REJECTED}),
}


def _build_allowed() -> dict[RequestStatus, frozenset[RequestStatus]]:
    """Полная карта переходов: база §7 + `CANCELLED` для каждого нетерминального.

    Гарантирует наличие записи для КАЖДОГО `RequestStatus` (включая терминальные →
    пустое множество), чтобы `allowed_transitions` никогда не падал на KeyError.
    """
    allowed: dict[RequestStatus, frozenset[RequestStatus]] = {}
    for status in RequestStatus:
        targets = _BASE_TRANSITIONS.get(status, frozenset())
        if status not in TERMINAL_STATUSES:
            targets = targets | {_S.CANCELLED}
        allowed[status] = targets
    return allowed


#: Итоговая карта допустимых переходов (источник истины для `allowed_transitions`).
ALLOWED_TRANSITIONS: dict[RequestStatus, frozenset[RequestStatus]] = _build_allowed()


def allowed_transitions(status: RequestStatus) -> frozenset[RequestStatus]:
    """Множество статусов, в которые можно перейти из `status` (для API-карточки)."""
    return ALLOWED_TRANSITIONS[status]


def is_terminal(status: RequestStatus) -> bool:
    """Является ли статус терминальным (нет исходящих переходов)."""
    return status in TERMINAL_STATUSES


def can_transition(source: RequestStatus, target: RequestStatus) -> bool:
    """Разрешён ли переход `source → target` по §7."""
    return target in ALLOWED_TRANSITIONS[source]


def ensure_transition(source: RequestStatus, target: RequestStatus) -> None:
    """Проверить переход; запрещённый → 409 (ТЗ §7, без ПДн в detail)."""
    if not can_transition(source, target):
        raise ProblemException.conflict(
            detail=f"Transition {source.value} -> {target.value} is not allowed"
        )
