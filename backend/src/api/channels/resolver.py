"""Резолвер канала: `PartnerChannelConfig` → готовый `DeliveryChannel` (§9.2).

Изолирует жизненный цикл сетевых клиентов: для API открывает httpx на endpoint
партнёра (закрывается по выходу из контекста), для MOCK — без сети. Реальные
SDK-каналы (CRM/Telegram/MAX/Email) — отдельными ADR; до этого `resolve` для них
бросает `NotImplementedError` (диспетчер фиксирует попытку как FAILED и идёт дальше).
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from api.channels.adapters.mock import MockChannel
from api.channels.adapters.partner_api import PartnerApiChannel
from api.channels.enums import ChannelType
from api.channels.models import PartnerChannelConfig
from api.channels.protocol import ChannelConfig, DeliveryChannel
from api.clients.auth import StaticTokenProvider
from api.clients.factory import build_resilient_client
from api.config import Settings


def to_channel_config(orm: PartnerChannelConfig) -> ChannelConfig:
    """Спроецировать ORM-конфигурацию в DTO канала (§6.4)."""
    return ChannelConfig(
        collaborator_id=orm.collaborator_id,
        channel_type=orm.channel_type,
        priority=orm.priority,
        config=orm.config,
        inbound_token=orm.inbound_token,
        is_active=orm.is_active,
    )


class ChannelResolver(Protocol):
    """Фабрика каналов: даёт `DeliveryChannel` как async-контекст (управляет httpx)."""

    def resolve(
        self, config: PartnerChannelConfig
    ) -> contextlib.AbstractAsyncContextManager[DeliveryChannel]: ...


class HttpChannelResolver:
    """Боевой резолвер: MOCK → MockChannel; API → PartnerApiChannel поверх httpx."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(
        self, config: PartnerChannelConfig
    ) -> contextlib.AbstractAsyncContextManager[DeliveryChannel]:
        if config.channel_type is ChannelType.MOCK:
            return self._mock()
        if config.channel_type is ChannelType.API:
            return self._partner_api(config)
        raise NotImplementedError(f"channel {config.channel_type.value} requires an ADR")

    @contextlib.asynccontextmanager
    async def _mock(self) -> AsyncIterator[DeliveryChannel]:
        yield MockChannel()

    @contextlib.asynccontextmanager
    async def _partner_api(self, config: PartnerChannelConfig) -> AsyncIterator[DeliveryChannel]:
        endpoint = str(config.config["endpoint"])
        # Токен — из kb-vault по ссылке; на dev/test — плейсхолдер из конфига канала.
        token = str(config.config.get("auth_token", ""))
        async with httpx.AsyncClient(
            base_url=endpoint, timeout=self._settings.client_timeout_seconds
        ) as http:
            resilient = build_resilient_client("partner_api", http, self._settings)
            yield PartnerApiChannel(resilient, StaticTokenProvider(token))
