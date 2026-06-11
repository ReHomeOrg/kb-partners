"""Интерфейс `DeliveryChannel` и DTO (§9.1).

Каналы НЕ зависят от ORM-модели `ServiceRequest` (развязка): dispatch-слой строит
`DeliveryPayload` с МИНИМАЛЬНО необходимым составом по категории (FR-4.6) и
`ChannelConfig` из `PartnerChannelConfig`. `provider_response` каналов — без ПДн.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus


@dataclass(frozen=True)
class ChannelConfig:
    """Конфигурация канала партнёра (проекция `PartnerChannelConfig`, §6.4).

    `config` — endpoint/chat_id/email/шаблоны; **секреты — ссылкой на kb-vault**,
    не инлайн. `inbound_token` — секрет верификации входящих (HMAC).
    """

    collaborator_id: str
    channel_type: ChannelType
    priority: int
    config: dict[str, Any]
    inbound_token: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class DeliveryPayload:
    """Состав, передаваемый партнёру (FR-4.6: минимально необходимый по категории).

    Только обезличенное/служебное: номер, категория, маскированное описание,
    структурированные параметры и ссылки на вложения (kb-files). Без сырых ПДн.
    """

    request_id: str
    number: str
    category: str
    summary: str
    params: dict[str, Any]
    idempotency_key: str
    attachments: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeliveryResult:
    """Итог доставки. `provider_response` — без ПДн (статусы/ссылки, не тело партнёра)."""

    outcome: DeliveryOutcome
    provider_response: dict[str, Any]
    external_ref: str | None = None


@dataclass(frozen=True)
class StatusUpdate:
    """Разобранное входящее от партнёра (E5): ссылка на заявку + исход."""

    request_ref: str
    outcome: DeliveryOutcome
    raw: dict[str, Any]


@dataclass(frozen=True)
class Health:
    """Результат healthcheck канала (§9.3)."""

    status: HealthStatus
    detail: str | None = None


@runtime_checkable
class DeliveryChannel(Protocol):
    """Канал доставки: исходящее (`deliver`), разбор входящего, healthcheck (§9.1)."""

    channel_type: ChannelType

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult: ...

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None: ...

    async def healthcheck(self, config: ChannelConfig) -> Health: ...
