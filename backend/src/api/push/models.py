"""ORM-модель web-push подписки браузера (E8, ADR-0004).

Своя таблица (арх-константа). Хранит endpoint + ключи шифрования (p256dh/auth) —
это НЕ ПДн (анонимные ключи push-сервиса браузера), но доступ ограничен владельцем.
`owner_id` — requester_id (заявитель) или partner_id (партнёр); `audience` различает
контур. Пара (owner_id, endpoint) уникальна (идемпотентная регистрация).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from api.db.base import Base


class PushSubscription(Base):
    """Подписка браузера на web-push (один эндпоинт push-сервиса на устройство)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    audience: Mapped[str] = mapped_column(String(32), nullable=False)  # user | partner
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(Text, nullable=False)
    auth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("uq_push_subscriptions_owner_endpoint", "owner_id", "endpoint", unique=True),
    )
