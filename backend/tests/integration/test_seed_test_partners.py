"""Интеграционные тесты seed каналов тест-партнёров (acceptance A1, A4, A7).

Реальная БД (dev-порт 5434), изоляция — savepoint из conftest. Проверяем
идемпотентность upsert и состав записанных `PartnerChannelConfig`.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.enums import ChannelType
from api.channels.models import PartnerChannelConfig
from api.clients.platform.fixtures import TEST_COLLABORATOR_PREFIX, TEST_PARTNERS
from api.scripts.seed_test_partners import seed_test_partners

_LIKE = f"{TEST_COLLABORATOR_PREFIX}%"
_EXPECTED_PARTNERS = 5
_EXPECTED_CHANNELS = 9  # 4 профиля × (telegram+email) + 1 агрегатор × api


async def _channels_for(session: AsyncSession, collaborator_id: str) -> list[PartnerChannelConfig]:
    rows = await session.scalars(
        select(PartnerChannelConfig)
        .where(PartnerChannelConfig.collaborator_id == collaborator_id)
        .order_by(PartnerChannelConfig.priority)
    )
    return list(rows)


async def test_seed_is_idempotent(session: AsyncSession) -> None:
    # A1: двойной прогон не плодит дублей — 5 партнёров, 9 каналов, без дублей.
    first = await seed_test_partners(session)
    second = await seed_test_partners(session)
    assert first == second == _EXPECTED_CHANNELS

    partners = await session.scalar(
        select(func.count(func.distinct(PartnerChannelConfig.collaborator_id))).where(
            PartnerChannelConfig.collaborator_id.like(_LIKE)
        )
    )
    channels = await session.scalar(
        select(func.count())
        .select_from(PartnerChannelConfig)
        .where(PartnerChannelConfig.collaborator_id.like(_LIKE))
    )
    assert partners == _EXPECTED_PARTNERS
    assert channels == _EXPECTED_CHANNELS


async def test_all_rows_tagged_test(session: AsyncSession) -> None:
    # A2 (сторона БД): все засеянные каналы — под префиксом `test-`.
    await seed_test_partners(session)
    all_ids = await session.scalars(select(PartnerChannelConfig.collaborator_id))
    test_ids = [cid for cid in all_ids if cid.startswith(TEST_COLLABORATOR_PREFIX)]
    assert len(test_ids) == _EXPECTED_CHANNELS


async def test_profile_channels_telegram_then_email(session: AsyncSession) -> None:
    # A4: профильные партнёры — TELEGRAM(prio1)+EMAIL(prio2).
    await seed_test_partners(session)
    for collaborator_id in (
        "test-chistyakoff",
        "test-delikatny-pereezd-spb",
        "test-delikatny-pereezd-msk",
        "test-lenremont",
    ):
        channels = await _channels_for(session, collaborator_id)
        assert [c.channel_type for c in channels] == [ChannelType.TELEGRAM, ChannelType.EMAIL]
        assert [c.priority for c in channels] == [1, 2]
        assert all(c.is_active for c in channels)


async def test_aggregator_channel_is_api(session: AsyncSession) -> None:
    # A4: Профи.ру — единственный канал API(prio1).
    await seed_test_partners(session)
    channels = await _channels_for(session, "test-profi-ru")
    assert len(channels) == 1
    assert channels[0].channel_type is ChannelType.API
    assert channels[0].priority == 1


async def test_no_secrets_in_db(session: AsyncSession) -> None:
    # A7: в config нет токенов/ключей — только ENV:-ссылки; inbound_token не пишется.
    await seed_test_partners(session)
    rows = await _channels_for_all_test(session)
    assert rows  # засеяли
    for row in rows:
        blob = json.dumps(row.config, ensure_ascii=False)
        # Любая ссылка на секрет — строго `ENV:<NAME>`-маркером.
        for key in ("bot_token_ref", "auth_ref"):
            if key in row.config:
                assert str(row.config[key]).startswith("ENV:")
        # Нет «голых» значений секретов и сырого inbound_token.
        assert "TG_BOT_TOKEN_TEST" not in blob or "ENV:TG_BOT_TOKEN_TEST" in blob
        assert row.inbound_token is None


async def _channels_for_all_test(session: AsyncSession) -> list[PartnerChannelConfig]:
    rows = await session.scalars(
        select(PartnerChannelConfig).where(PartnerChannelConfig.collaborator_id.like(_LIKE))
    )
    return list(rows)


def test_fixture_count_matches_expected() -> None:
    # Страховка инварианта: 9 каналов = сумма seed_channels по всем тест-партнёрам.
    total = sum(len(p.seed_channels) for p in TEST_PARTNERS)
    assert total == _EXPECTED_CHANNELS
