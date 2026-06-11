"""Доменные перечисления ядра заявки `ServiceRequest` (ТЗ §6–§7).

Значения enum'ов — стабильный контракт (API / БД / история). В БД хранятся как
VARCHAR (`Enum(..., native_enum=False)` без CHECK-constraint): добавление статуса
или категории в эпиках M2+ не должно требовать `ALTER TYPE` / миграции данных;
валидность гарантируется приложением (Pydantic-схемы) и FSM (§7).
"""

from __future__ import annotations

import enum


class ChannelIn(str, enum.Enum):
    """Канал приёма заявки (§6.1 `channel_in`, эпик E1)."""

    WEB_FORM = "WEB_FORM"
    AI_CHAT = "AI_CHAT"
    SUPPORT_TICKET = "SUPPORT_TICKET"
    API = "API"
    MESSENGER_INBOUND = "MESSENGER_INBOUND"


class Category(str, enum.Enum):
    """Категория услуги (§6.1 `category`, эпик E2).

    Соответствует группе B реестра `Collaborator` в kb-platform (cleaning / moving /
    repair_handyman / key_delivery, ADR-0002). `OTHER` — нераспознанное / ручной разбор.
    """

    CLEANING = "CLEANING"
    MOVING = "MOVING"
    REPAIR = "REPAIR"
    KEY_DELIVERY = "KEY_DELIVERY"
    OTHER = "OTHER"


class RequestStatus(str, enum.Enum):
    """Статус заявки — состояние FSM (§7). Допустимые переходы — в `api.requests.fsm`."""

    NEW = "NEW"
    CLASSIFYING = "CLASSIFYING"
    CLASSIFIED = "CLASSIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    MATCHING = "MATCHING"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    FAILED_DISPATCH = "FAILED_DISPATCH"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    ACCEPTED_BY_USER = "ACCEPTED_BY_USER"
    DISPUTE = "DISPUTE"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AccessLevel(str, enum.Enum):
    """Контур доступа ресурса (§12 двухконтурность; недоступное → 404, не 403)."""

    PUBLIC = "PUBLIC"
    LOGGED = "LOGGED"
    AGENT = "AGENT"
    STAFF = "STAFF"
    LEGAL = "LEGAL"
    HR_RESTRICTED = "HR_RESTRICTED"


class AuthorType(str, enum.Enum):
    """Автор сообщения заявки (§6.2 `author_type`)."""

    REQUESTER = "REQUESTER"
    OPERATOR = "OPERATOR"
    PARTNER = "PARTNER"
    SYSTEM = "SYSTEM"
    AI = "AI"


class HistoryAction(str, enum.Enum):
    """Тип записи неизменяемого аудита (§6.3 `action`).

    Минимальный набор для M1 (приём, переход FSM, сообщение). Расширяется по мере
    эпиков (классификация / назначение / диспетчеризация) — хранение VARCHAR
    позволяет добавлять значения без миграции.
    """

    CREATED = "CREATED"
    STATUS_CHANGED = "STATUS_CHANGED"
    MESSAGE_ADDED = "MESSAGE_ADDED"
    CLASSIFIED = "CLASSIFIED"
