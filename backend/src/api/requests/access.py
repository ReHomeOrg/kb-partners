"""Политика доступа к заявкам (§12 двухконтурность, CLAUDE.md правила 9–10).

Два независимых измерения, оба применяются на уровне ХРАНИЛИЩА:
- **access_level** заявки (PUBLIC…HR_RESTRICTED) ↔ допуск субъекта;
- **владение**: заявитель видит свои, партнёр — назначенные, агент — заявки
  пользователя, от чьего имени действует (on-behalf-of, FR-9.7), оператор — все.

Невидимый ресурс → **404, не 403** (анти-enumeration). Действие над ВИДИМЫМ
ресурсом без прав → 403 (это решает сервисный слой после проверки видимости).

`is_internal`-заметки и ПДн-исходник (`raw_input`) — отдельные ужесточения видимости.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement

from api.auth.principal import Principal
from api.requests.enums import AccessLevel
from api.requests.models import ServiceRequest

_ALL_LEVELS: frozenset[AccessLevel] = frozenset(AccessLevel)
_AGENT_LEVELS: frozenset[AccessLevel] = frozenset(
    {AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}
)
_BASE_LEVELS: frozenset[AccessLevel] = frozenset({AccessLevel.PUBLIC, AccessLevel.LOGGED})


def visible_access_levels(principal: Principal) -> frozenset[AccessLevel]:
    """Допуски субъекта по контуру `access_level`."""
    if principal.is_operator or principal.is_staff_admin:
        return _ALL_LEVELS
    if principal.is_agent:
        return _AGENT_LEVELS
    return _BASE_LEVELS


def ownership_condition(principal: Principal) -> ColumnElement[bool] | None:
    """SQL-условие владения (фильтр на хранилище). `None` — оператор видит все."""
    if principal.is_operator or principal.is_staff_admin:
        return None
    if principal.is_partner and principal.partner_id is not None:
        return ServiceRequest.partner_id == principal.partner_id
    if principal.is_agent and principal.on_behalf_of is not None:
        return ServiceRequest.requester_id == str(principal.on_behalf_of)
    return ServiceRequest.requester_id == str(principal.user_id)


def can_view_internal(principal: Principal) -> bool:
    """Внутренние заметки (`is_internal=True`) видят только операторы/стафф (правило 10)."""
    return principal.is_operator or principal.is_staff_admin


def can_see_raw_input(principal: Principal, request: ServiceRequest) -> bool:
    """ПДн-исходник: оператор, владелец-заявитель, агент от имени владельца.

    Партнёр исходник не видит (минимальный состав по категории — FR-4.6); ему в
    карточке отдаётся `raw_input_masked`.
    """
    if principal.is_operator or principal.is_staff_admin:
        return True
    if principal.is_partner:
        return False
    if principal.is_agent and principal.on_behalf_of is not None:
        return request.requester_id == str(principal.on_behalf_of)
    return request.requester_id == str(principal.user_id)


def can_drive_lifecycle(principal: Principal) -> bool:
    """Произвольные переходы FSM (`/transition`) — оператор или агент (E9 уточнит autonomy)."""
    return principal.is_operator or principal.is_staff_admin or principal.is_agent


def can_cancel(principal: Principal) -> bool:
    """Отмена доступна пользователю/оператору/агенту, но не партнёру-исполнителю (§11.1)."""
    return not principal.is_partner


def can_user_action(principal: Principal) -> bool:
    """Приёмка/спор — действия пользователя/оператора (FR-7.1/7.2), не партнёра."""
    return not principal.is_partner
