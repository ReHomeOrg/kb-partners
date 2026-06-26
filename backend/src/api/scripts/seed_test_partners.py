"""Идемпотентный seed каналов тестовых партнёров (dev/test).

Заводит `PartnerChannelConfig` для 5 тест-партнёров из `clients.platform.fixtures`
(см. документ `reHome_Консьерж_тестовые_партнёры.md`). Upsert по натуральному ключу
`(collaborator_id, channel_type)` — повторный прогон не плодит дублей (acceptance A1).

Только своя таблица `partner_channel_configs` (арх-константа ADR-0001 соблюдена).
Мастер-записи Collaborator (реестр) живут в kb-platform; здесь — лишь конфигурация
каналов доставки. Секреты не пишутся: в `config` только `ENV:`-ссылки (A7).

Запуск:
    make seed-test-partners
    python -m api.scripts.seed_test_partners
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.models import PartnerChannelConfig
from api.clients.platform.fixtures import TEST_COLLABORATOR_PREFIX, TEST_PARTNERS
from api.db import async_session_factory
from api.observability.logging import get_logger

_logger = get_logger("scripts.seed_test_partners")

_CONFLICT_CONSTRAINT = "uq_partner_channel_collaborator_type"


async def seed_test_partners(session: AsyncSession) -> int:
    """Upsert каналов всех тест-партнёров. Возвращает число обработанных строк-каналов."""
    rows: list[dict[str, Any]] = [
        {
            "id": uuid.uuid4(),  # PK для нового ряда; при конфликте отбрасывается
            "collaborator_id": partner.collaborator_id,
            "channel_type": channel.channel_type,
            "priority": channel.priority,
            "config": channel.config,
            "is_active": True,
        }
        for partner in TEST_PARTNERS
        for channel in partner.seed_channels
    ]
    stmt = pg_insert(PartnerChannelConfig).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint=_CONFLICT_CONSTRAINT,
        set_={
            "priority": stmt.excluded.priority,
            "config": stmt.excluded.config,
            "is_active": stmt.excluded.is_active,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(rows)


async def _count_test_channels(session: AsyncSession) -> tuple[int, int]:
    """(уникальных collaborator_id, всего строк-каналов) с префиксом `test-`."""
    like = f"{TEST_COLLABORATOR_PREFIX}%"
    partners = await session.scalar(
        select(func.count(func.distinct(PartnerChannelConfig.collaborator_id))).where(
            PartnerChannelConfig.collaborator_id.like(like)
        )
    )
    channels = await session.scalar(
        select(func.count())
        .select_from(PartnerChannelConfig)
        .where(PartnerChannelConfig.collaborator_id.like(like))
    )
    return int(partners or 0), int(channels or 0)


async def _main() -> None:
    async with async_session_factory() as session:
        upserted = await seed_test_partners(session)
        partners, channels = await _count_test_channels(session)
    _logger.info(
        "seed test partners done: upserted=%d test_partners=%d test_channels=%d",
        upserted,
        partners,
        channels,
    )


if __name__ == "__main__":
    asyncio.run(_main())
