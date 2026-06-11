"""ORM-модели каналов: `PartnerChannelConfig` (§6.4), `DispatchAttempt` (§6.5).

Своя БД (арх-константа): `collaborator_id` — строковая ссылка на kb-platform, не FK.
Секреты (`inbound_token`, креды в `config`) — в проде ссылками на kb-vault; в выдачу
наружу `inbound_token` НЕ попадает (см. схемы).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from api.channels.enums import ChannelType, DeliveryOutcome
from api.db.base import Base, TimestampMixin

_ENUM_LEN = 32


class PartnerChannelConfig(Base, TimestampMixin):
    """Конфигурация канала доставки на партнёра (§6.4). Админ-ресурс (staff)."""

    __tablename__ = "partner_channel_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    collaborator_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Секрет верификации входящих (HMAC). Наружу не отдаётся.
    inbound_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Последний healthcheck: {status, detail, checked_at}.
    health: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "collaborator_id", "channel_type", name="uq_partner_channel_collaborator_type"
        ),
    )


class DispatchAttempt(Base):
    """Попытка доставки заявки партнёру по каналу (§6.5). Неизменяемая запись."""

    __tablename__ = "dispatch_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("service_requests.id"), nullable=False, index=True
    )
    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DeliveryOutcome] = mapped_column(
        Enum(DeliveryOutcome, native_enum=False, length=_ENUM_LEN), nullable=False
    )
    # Ответ провайдера БЕЗ ПДн (статусы/ссылки, не тело партнёра).
    provider_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    outbox_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ts: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        # Идемпотентность попытки: ключ уникален (повтор доставки не плодит запись).
        Index("uq_dispatch_attempts_idempotency_key", "idempotency_key", unique=True),
    )
