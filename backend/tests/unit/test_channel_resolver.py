"""Юнит-тесты HttpChannelResolver (§9.2): MOCK/API строятся, неподдержанные → ADR."""

from __future__ import annotations

import pytest

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


def test_resolve_unsupported_requires_adr() -> None:
    resolver = HttpChannelResolver(Settings())
    with pytest.raises(NotImplementedError):
        resolver.resolve(_cfg(ChannelType.EMAIL))


def test_to_channel_config_projection() -> None:
    dto = to_channel_config(_cfg(ChannelType.API, endpoint="http://x"))
    assert dto.collaborator_id == "c-1"
    assert dto.channel_type is ChannelType.API
    assert dto.config == {"endpoint": "http://x"}
