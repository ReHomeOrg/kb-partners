"""ORM-модели ядра заявки (ТЗ §6.1–§6.3): `ServiceRequest`, `RequestMessage`,
`RequestHistory`.

Хранилище — собственная БД kb-partners (арх-константа, ADR-0001): никаких FK/JOIN
к чужим таблицам (`collaborators`, `service_orders`, `users`, `premises`). Связи с
соседями — только строковые ссылки-идентификаторы (`partner_id`, `service_order_id`,
`booking_id`, ...), резолвятся по HTTP через `api/clients/` (M2+).

Enum-поля хранятся как VARCHAR (`native_enum=False`, см. `enums.py`). JSONB — для
полей переменной структуры (трассировка классификации/подбора, SLA, source_ref).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base, TimestampMixin
from api.requests.enums import (
    AccessLevel,
    AuthorType,
    Category,
    ChannelIn,
    HistoryAction,
    RequestStatus,
)

# Длина VARCHAR-колонок enum'ов. С запасом над самым длинным значением
# (MESSENGER_INBOUND = 17): добавление новых значений не требует ALTER.
_ENUM_LEN = 32


def _uuid_pk() -> Mapped[uuid.UUID]:
    """UUID-первичный ключ (генерируется приложением, v4)."""
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ServiceRequest(Base, TimestampMixin):
    """Заявка-на-услугу (§6.1) — корневая сущность модуля и носитель FSM (§7).

    `access_level` обеспечивает двухконтурность (§12): фильтрация на уровне
    хранилища, недоступный ресурс → 404. `raw_input` содержит ПДн и подчиняется
    ретенции (NFR-12); в логи и LLM попадает только `raw_input_masked` (FR-1.6).
    """

    __tablename__ = "service_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Человекочитаемый номер (напр. RQ-00000042). Присваивается при приёме (M1.2)
    # из последовательности `service_request_number_seq`. Уникален.
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)

    # --- Контекст заявителя (строковые ссылки на rehome.one; не FK, арх-константа) ---
    requester_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    booking_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    premises_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Приём (E1) ---
    channel_in: Mapped[ChannelIn] = mapped_column(
        Enum(ChannelIn, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    source_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    raw_input_masked: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Классификация (E2) ---
    category: Mapped[Category | None] = mapped_column(
        Enum(Category, native_enum=False, length=_ENUM_LEN), nullable=True
    )
    product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    classification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- Подбор и диспетчеризация (E3/E4) ---
    partner_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    match_trace: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fallback_chain: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    delivery_channel: Mapped[str | None] = mapped_column(String(_ENUM_LEN), nullable=True)
    service_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Состояние (FSM §7) ---
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, native_enum=False, length=_ENUM_LEN),
        nullable=False,
        default=RequestStatus.NEW,
        index=True,
    )

    # --- SLA (E6) и денежные ССЫЛКИ контура (суммы НЕ считаем, ADR-0002) ---
    sla: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    amount_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    escrow_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Связи с kb-support (спор/претензия) и отзыв (E7) ---
    dispute_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    claim_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Прочее / двухконтурность / идемпотентность приёма ---
    custom_fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    access_level: Mapped[AccessLevel] = mapped_column(
        Enum(AccessLevel, native_enum=False, length=_ENUM_LEN),
        nullable=False,
        default=AccessLevel.LOGGED,
    )
    # Дедуп приёма (Idempotency-Key / chat_session_id). NULL допускает несколько
    # строк (PG не считает NULL равными) — уникальность только для заполненных.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Таймстемпы жизненного цикла (created_at/updated_at — из TimestampMixin) ---
    dispatched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    done_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_by_user_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Идемпотентность приёма: уникален заполненный ключ (NULL не участвует).
        Index(
            "uq_service_requests_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=idempotency_key.isnot(None),
        ),
        Index("ix_service_requests_category", "category"),
        Index("ix_service_requests_created_at", "created_at"),
    )


class RequestMessage(Base):
    """Сообщение / внутренняя заметка по заявке (§6.2).

    **Критичный инвариант:** `is_internal=True` — внутренняя заметка, НЕвидимая
    заявителю и партнёру (CLAUDE.md правило 10). Фильтрация по видимости — на уровне
    хранилища/сервиса (M1.3), с обязательным security-тестом.
    """

    __tablename__ = "request_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("service_requests.id"),
        nullable=False,
        index=True,
    )
    author_type: Mapped[AuthorType] = mapped_column(
        Enum(AuthorType, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    # Атрибуция автора (user_id / partner_id / сервис-принципал). NULL для system.
    author_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Ссылки на вложения в kb-files (по API, не shared bucket — арх-константа).
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RequestHistory(Base):
    """Неизменяемый аудит изменений заявки (§6.3).

    Каждое значимое действие (создание, переход FSM, добавление сообщения) → строка.
    `actor_id` — NOT NULL (инвариант «у каждой записи есть актор»): реальный user-id
    либо системный sentinel из `api.auth.system_actors`. Записи не обновляются и не
    удаляются (append-only); ретенция аудита — отдельной политикой (NFR-12).
    """

    __tablename__ = "request_history"

    id: Mapped[uuid.UUID] = _uuid_pk()
    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("service_requests.id"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[HistoryAction] = mapped_column(
        Enum(HistoryAction, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    from_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
