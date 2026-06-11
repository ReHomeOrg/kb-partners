"""Dramatiq-акторы: дрейн transactional outbox (NFR-8).

Актор инертен без реального брокера/воркера (StubBroker). Делегирует чистую async-
логику дрейна, обёрнутую `asyncio.run` (актор — sync-функция). ops триггерит актор
периодически (cron/планировщик) для добора PENDING-сообщений после сбоев.
"""

from __future__ import annotations

import asyncio

import dramatiq

from api.channels.dispatch import drain_dispatch_batch
from api.channels.resolver import HttpChannelResolver
from api.config import get_settings
from api.db import async_session_factory
from api.observability.logging import get_logger
from api.sla.engine import SlaPolicy
from api.tasks.broker import broker  # noqa: F401 — импорт устанавливает брокер

_logger = get_logger("tasks.outbox")


async def _drain_dispatch() -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        return await drain_dispatch_batch(
            session,
            resolver=HttpChannelResolver(settings),
            policy=SlaPolicy.from_settings(settings),
            settings=settings,
        )


@dramatiq.actor(max_retries=0)
def drain_outbox_dispatch() -> None:
    """Добрать PENDING `dispatch`-сообщения из outbox (durable-доставка)."""
    processed = asyncio.run(_drain_dispatch())
    _logger.info("outbox dispatch drain: processed=%d", processed)
