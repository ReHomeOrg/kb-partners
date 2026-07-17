"""Модель аутентифицированного субъекта (`Principal`) для RBAC kb-partners.

Результат верификации токена/сессии. Интерфейс зафиксирован на M0; реальный
верификатор (Keycloak JWT RS256/JWKS) наполняет модель из проверенных клеймов.

См. ADR-0001 (арх-константа), §12 ТЗ (RBAC, scope считается бэкендом из
проверенного токена — не из payload и не с фронтенда).
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from api.auth.scopes import AGENT_SCOPE, OPERATOR_SCOPE, PARTNER_SCOPE, STAFF_ADMIN_SCOPE


class PrincipalKind(str, enum.Enum):
    """Тип субъекта.

    REQUESTER — заявитель (видит только свои заявки). OPERATOR — сотрудник
    (рабочее место оператора). PARTNER — исполнитель (портал LIGHT, видит только
    свои заявки). SERVICE — m2m-вызов (kb-search/kb-support/входящий API). AGENT —
    ИИ-агент-оркестратор «Консьерж» (действует on-behalf-of пользователя, FR-9.7).
    """

    REQUESTER = "requester"
    OPERATOR = "operator"
    PARTNER = "partner"
    SERVICE = "service"
    AGENT = "agent"


@dataclass(frozen=True)
class Principal:
    """Аутентифицированный субъект запроса.

    `partner_id` заполняется для субъектов PARTNER и ограничивает видимость
    заявок партнёра (storage-level фильтр, §12). `on_behalf_of` — sub пользователя,
    от имени которого действует агент (**легаси** `kbp_act_sub`, FR-9.7).
    `acting_agent` — clientId агента из стандартного RFC 8693 `act.sub` (новая схема
    CC-1: `sub` уже = пользователь, `act.sub` лишь фиксирует, что действует агент).
    Легаси `on_behalf_of` и новый `acting_agent` **взаимоисключающие** (одновременно
    в токене → 401 в верификаторе). `scopes` — гранулярные права из токена.
    """

    user_id: uuid.UUID
    kind: PrincipalKind
    scopes: frozenset[str] = field(default_factory=frozenset)
    partner_id: str | None = None
    on_behalf_of: uuid.UUID | None = None
    acting_agent: str | None = None

    @property
    def is_operator(self) -> bool:
        """Является ли субъект оператором (доступ к рабочему месту)."""
        return self.kind is PrincipalKind.OPERATOR or OPERATOR_SCOPE in self.scopes

    @property
    def is_partner(self) -> bool:
        """Является ли субъект партнёром-исполнителем (портал LIGHT, E10)."""
        return self.kind is PrincipalKind.PARTNER or PARTNER_SCOPE in self.scopes

    @property
    def is_agent(self) -> bool:
        """Является ли субъект ИИ-агентом-оркестратором (E9, tools-эндпоинты).

        True для легаси-схемы (`kbp_kind=agent`/`AGENT_SCOPE`) и для новой
        (стандартный `act.sub` — `acting_agent` заполнен)."""
        return (
            self.kind is PrincipalKind.AGENT
            or self.acting_agent is not None
            or AGENT_SCOPE in self.scopes
        )

    @property
    def is_staff_admin(self) -> bool:
        """Есть ли у субъекта админ-скоуп (каналы/правила/SLA-конфигурация)."""
        return STAFF_ADMIN_SCOPE in self.scopes
