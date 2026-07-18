"""Тесты потребления делегирования CC-1 в фильтрах доступа (§12, G7).

Проверяют, что новая схема `act.sub` (агент действует, `sub` уже = пользователь,
`on_behalf_of=None`, `acting_agent` задан) даёт правильную связку контур∧владение:
видимость AGENT-контура **только среди своих** заявок (не эскалация привилегий).
"""

from __future__ import annotations

import uuid

from api.auth.principal import Principal, PrincipalKind
from api.requests.access import ownership_condition, visible_access_levels
from api.requests.enums import AccessLevel


def _ownership_sql(principal: Principal) -> str:
    cond = ownership_condition(principal)
    assert cond is not None
    return str(cond.compile(compile_kwargs={"literal_binds": True}))


def test_new_scheme_agent_visibility_is_agent_levels_scoped_to_owner() -> None:
    # Новая схема: is_agent=True → контур {PUBLIC, LOGGED, AGENT}, НО владение = свои
    # заявки пользователя (requester_id == user_id), т.к. on_behalf_of=None.
    user_sub = uuid.uuid4()
    principal = Principal(
        user_id=user_sub, kind=PrincipalKind.REQUESTER, acting_agent="kb-concierge-m2m"
    )
    assert principal.is_agent is True
    assert visible_access_levels(principal) == frozenset(
        {AccessLevel.PUBLIC, AccessLevel.LOGGED, AccessLevel.AGENT}
    )
    sql = _ownership_sql(principal)
    assert str(user_sub) in sql


def test_direct_user_does_not_see_agent_contour() -> None:
    # Прямой пользователь (без агента) — только BASE-контур, AGENT не виден.
    principal = Principal(user_id=uuid.uuid4(), kind=PrincipalKind.REQUESTER)
    assert principal.is_agent is False
    assert visible_access_levels(principal) == frozenset(
        {AccessLevel.PUBLIC, AccessLevel.LOGGED}
    )


def test_legacy_agent_ownership_uses_delegated_user() -> None:
    # Легаси-схема без изменений: on_behalf_of=пользователь → владение по нему.
    agent_sub = uuid.uuid4()
    user_sub = uuid.uuid4()
    principal = Principal(user_id=agent_sub, kind=PrincipalKind.AGENT, on_behalf_of=user_sub)
    sql = _ownership_sql(principal)
    assert str(user_sub) in sql
    assert str(agent_sub) not in sql
