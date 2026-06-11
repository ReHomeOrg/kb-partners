"""Pydantic-схемы конфигурации каналов (§11.2). `inbound_token` наружу не отдаётся."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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
