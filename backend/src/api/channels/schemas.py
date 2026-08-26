"""Pydantic-схемы конфигурации каналов (§11.2). `inbound_token` наружу не отдаётся."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from api.channels.enums import ChannelType

_MAX_ID = 255


class ChannelConfigCreate(BaseModel):
    """Тело `POST /channels` (admin)."""

    model_config = ConfigDict(extra="forbid")

    collaborator_id: str = Field(min_length=1, max_length=_MAX_ID)
    channel_type: ChannelType
    priority: int = Field(default=100, ge=0)
    config: dict[str, Any] = Field(default_factory=dict)
    inbound_token: str | None = Field(default=None, max_length=_MAX_ID)
    is_active: bool = True


class ChannelConfigUpdate(BaseModel):
    """Тело `PATCH /channels/{id}` — частичное обновление (admin)."""

    model_config = ConfigDict(extra="forbid")

    priority: int | None = Field(default=None, ge=0)
    config: dict[str, Any] | None = None
    inbound_token: str | None = Field(default=None, max_length=_MAX_ID)
    is_active: bool | None = None


class InboundEnvelope(BaseModel):
    """Стандартный конверт входящего от партнёра (E5). Подпись/таймстемп — в заголовках."""

    model_config = ConfigDict(extra="ignore")

    request_ref: str = Field(min_length=1, max_length=_MAX_ID)
    # Статус необязателен: событие может нести только оценку. Партнёр назвал цену —
    # заявка при этом осталась на том же шаге, и двигать её FSM побочным эффектом
    # от ввода суммы нельзя.
    status: str | None = Field(default=None, min_length=1, max_length=64)
    nonce: str = Field(min_length=1, max_length=_MAX_ID)
    message: str | None = Field(default=None, max_length=20_000)
    # Оценка работ по факту осмотра (issue #6). Едет тем же конвертом: заводить
    # второй транспорт ради неё значило бы дублировать подпись, дедуп и корреляцию.
    estimate_amount: Decimal | None = Field(default=None, ge=0)
    estimate_note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _not_empty(self) -> InboundEnvelope:
        if (
            self.status is None
            and self.estimate_amount is None
            and not (self.estimate_note or "").strip()
        ):
            raise ValueError("нужен статус или оценка")
        return self


class ChannelConfigRead(BaseModel):
    """Представление конфигурации канала. БЕЗ `inbound_token` (секрет, не отдаём)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    collaborator_id: str
    channel_type: ChannelType
    priority: int
    config: dict[str, Any]
    is_active: bool
    health: dict[str, Any] | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
