"""Юнит-тесты HttpChannelResolver (§9.2): все боевые каналы строятся по типу."""

from __future__ import annotations

from api.channels.adapters.bot import MaxChannel, TelegramChannel
from api.channels.adapters.crm import AmoCrmChannel, Bitrix24Channel
from api.channels.adapters.email import EmailChannel
from api.channels.adapters.mock import MockChannel
from api.channels.adapters.partner_api import PartnerApiChannel
from api.channels.enums import ChannelType
from api.channels.models import PartnerChannelConfig
from api.channels.resolver import HttpChannelResolver, to_channel_config
from api.config import Settings


def _cfg(channel_type: ChannelType, **config: object) -> PartnerChannelConfig:
    return PartnerChannelConfig(
        collaborator_id="c-1",
        channel_type=channel_type,
        priority=1,
        config=dict(config),
        is_active=True,
    )


async def test_resolve_mock_channel() -> None:
    resolver = HttpChannelResolver(Settings())
    async with resolver.resolve(_cfg(ChannelType.MOCK)) as channel:
        assert isinstance(channel, MockChannel)


async def test_resolve_partner_api_channel() -> None:
    resolver = HttpChannelResolver(Settings())
    config = _cfg(ChannelType.API, endpoint="http://partner.example", auth_token="t")
    async with resolver.resolve(config) as channel:
        assert isinstance(channel, PartnerApiChannel)


async def test_resolve_telegram_and_max() -> None:
    resolver = HttpChannelResolver(Settings())
    async with resolver.resolve(_cfg(ChannelType.TELEGRAM)) as channel:
        assert isinstance(channel, TelegramChannel)
    async with resolver.resolve(_cfg(ChannelType.MAX)) as channel:
        assert isinstance(channel, MaxChannel)


async def test_resolve_email_channel() -> None:
    resolver = HttpChannelResolver(Settings())
    async with resolver.resolve(_cfg(ChannelType.EMAIL)) as channel:
        assert isinstance(channel, EmailChannel)


async def test_resolve_crm_by_type() -> None:
    resolver = HttpChannelResolver(Settings())
    bitrix = _cfg(ChannelType.CRM, endpoint="http://portal.bitrix24.ru", crm_type="bitrix24")
    async with resolver.resolve(bitrix) as channel:
        assert isinstance(channel, Bitrix24Channel)
    amo = _cfg(ChannelType.CRM, endpoint="http://x.amocrm.ru", crm_type="amocrm")
    async with resolver.resolve(amo) as channel:
        assert isinstance(channel, AmoCrmChannel)


def test_to_channel_config_projection() -> None:
    dto = to_channel_config(_cfg(ChannelType.API, endpoint="http://x"))
    assert dto.collaborator_id == "c-1"
    assert dto.channel_type is ChannelType.API
    assert dto.config == {"endpoint": "http://x"}
