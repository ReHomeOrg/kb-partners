"""Dramatiq-акторы: дрейн transactional outbox (NFR-8).

Актор инертен без реального брокера/воркера (StubBroker). Делегирует чистую async-
логику дрейна, обёрнутую `asyncio.run` (актор — sync-функция). ops триггерит актор
периодически (cron/планировщик) для добора PENDING-сообщений после сбоев.
"""

from __future__ import annotations

import asyncio
import time

import dramatiq
import httpx

from api.automation.pipeline import AutomationDeps, drain_on_create_batch
from api.channels.dispatch import drain_dispatch_batch
from api.channels.resolver import HttpChannelResolver
from api.classifier.engine import ClassifierEngine
from api.classifier.provider import build_llm_provider
from api.clients.auth import StaticTokenProvider
from api.clients.cache import InMemoryCache
from api.clients.factory import build_resilient_client
from api.clients.platform.adapter import HttpPlatformClient
from api.config import Settings, get_settings
from api.db import async_session_factory
from api.matching.engine import Matcher
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


async def _drain_on_create() -> int:
    settings = get_settings()
    async with (
        httpx.AsyncClient(
            base_url=settings.platform_api_base_url, timeout=settings.client_timeout_seconds
        ) as http,
        async_session_factory() as session,
    ):
        platform = HttpPlatformClient(
            http_client=build_resilient_client("platform", http, settings),
            token_provider=StaticTokenProvider(settings.platform_api_token),
            cache=InMemoryCache(now=time.monotonic),
            cache_ttl_seconds=settings.platform_cache_ttl_seconds,
        )
        deps = _automation_deps(settings, platform)
        return await drain_on_create_batch(session, deps, settings=settings)


def _automation_deps(settings: Settings, platform: HttpPlatformClient) -> AutomationDeps:
    return AutomationDeps(
        engine=ClassifierEngine(build_llm_provider(settings.classifier_llm_provider)),
        confidence_threshold=settings.classifier_confidence_threshold,
        platform=platform,
        matcher=Matcher(),
        resolver=HttpChannelResolver(settings),
        policy=SlaPolicy.from_settings(settings),
        require_service_order=bool(settings.platform_api_token),
    )


@dramatiq.actor(max_retries=0)
def drain_outbox_dispatch() -> None:
    """Добрать PENDING `dispatch`-сообщения из outbox (durable-доставка)."""
    processed = asyncio.run(_drain_dispatch())
    _logger.info("outbox dispatch drain: processed=%d", processed)


@dramatiq.actor(max_retries=0)
def drain_outbox_on_create() -> None:
    """Прогнать on_create-пайплайн по поставленным задачам автоматизации (E6)."""
    processed = asyncio.run(_drain_on_create())
    _logger.info("outbox on_create drain: processed=%d", processed)
