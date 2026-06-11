"""Pydantic-схемы web-push API (E8, FR-10.1)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PushKeys(BaseModel):
    """Ключи шифрования подписки браузера (PushSubscription.getKey)."""

    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionCreate(BaseModel):
    """Регистрация подписки браузера на web-push (тело от Service Worker портала)."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeys


class PushSubscriptionAck(BaseModel):
    """Подтверждение регистрации/отписки."""

    status: str
