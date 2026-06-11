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

from api.automation.autonomy import parse_autonomy
from api.automation.pipeline import AutomationDeps, drain_on_create_batch
from api.automation.timers import drain_partner_fallback_batch, scan_accept_timeouts
from api.channels.dispatch import drain_dispatch_batch
from api.channels.email_inbound import EmailInboundService, ImaplibFetcher
from api.channels.resolver import HttpChannelResolver
from api.classifier.engine import ClassifierEngine
from api.classifier.yandexgpt import build_llm_provider
from api.clients.auth import build_token_provider
from api.clients.cache import InMemoryCache
from api.clients.factory import build_resilient_client
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.rehome.adapter import HttpRehomeOneClient
from api.config import Settings, get_settings
from api.db import async_session_factory
from api.matching.engine import Matcher
from api.notifications.contacts import NeighborContactResolver
from api.notifications.drainer import drain_notification_batch
from api.observability.logging import get_logger
from api.retention.worker import anonymize_expired_raw_input
from api.sla.engine import SlaPolicy
from api.tasks.broker import broker  # noqa: F401 — импорт устанавливает брокер
from api.webhooks.client import WebhookClient
from api.webhooks.drainer import drain_webhook_batch

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
            token_provider=build_token_provider(
                settings, fallback_token=settings.platform_api_token
            ),
            cache=InMemoryCache(now=time.monotonic),
            cache_ttl_seconds=settings.platform_cache_ttl_seconds,
        )
        deps = _automation_deps(settings, platform)
        return await drain_on_create_batch(session, deps, settings=settings)


def _automation_deps(settings: Settings, platform: HttpPlatformClient) -> AutomationDeps:
    return AutomationDeps(
        engine=ClassifierEngine(build_llm_provider(settings)),
        confidence_threshold=settings.classifier_confidence_threshold,
        platform=platform,
        matcher=Matcher(),
        resolver=HttpChannelResolver(settings),
        policy=SlaPolicy.from_settings(settings),
        require_service_order=bool(settings.platform_api_token),
        autonomy=parse_autonomy(settings.automation_autonomy_level),
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


async def _drain_webhooks() -> int:
    settings = get_settings()
    async with (
        httpx.AsyncClient(timeout=settings.client_timeout_seconds) as http,
        async_session_factory() as session,
    ):
        client = WebhookClient(
            build_resilient_client("webhook", http, settings),
            url=settings.webhook_url,
            secret=settings.webhook_secret,
        )
        return await drain_webhook_batch(session, client, settings=settings)


@dramatiq.actor(max_retries=0)
def drain_outbox_webhook() -> None:
    """Доставить исходящие webhooks подписчику (E8, после commit)."""
    processed = asyncio.run(_drain_webhooks())
    _logger.info("outbox webhook drain: processed=%d", processed)


async def _drain_notifications() -> int:
    settings = get_settings()
    async with (
        httpx.AsyncClient(
            base_url=settings.platform_api_base_url, timeout=settings.client_timeout_seconds
        ) as platform_http,
        httpx.AsyncClient(
            base_url=settings.rehome_one_api_base_url, timeout=settings.client_timeout_seconds
        ) as rehome_http,
        async_session_factory() as session,
    ):
        platform = HttpPlatformClient(
            http_client=build_resilient_client("platform", platform_http, settings),
            token_provider=build_token_provider(
                settings, fallback_token=settings.platform_api_token
            ),
            cache=InMemoryCache(now=time.monotonic),
            cache_ttl_seconds=settings.platform_cache_ttl_seconds,
        )
        rehome = HttpRehomeOneClient(
            http_client=build_resilient_client("rehome", rehome_http, settings),
            token_provider=build_token_provider(
                settings, fallback_token=settings.rehome_one_api_token
            ),
        )
        resolver = NeighborContactResolver(rehome=rehome, platform=platform, settings=settings)
        return await drain_notification_batch(session, settings=settings, resolver=resolver)


@dramatiq.actor(max_retries=0)
def drain_outbox_notification() -> None:
    """Разослать уведомления заявителю/партнёру/оператору по seam-каналам (E8)."""
    processed = asyncio.run(_drain_notifications())
    _logger.info("outbox notification drain: processed=%d", processed)


async def _scan_sla_timers() -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        return await scan_accept_timeouts(
            session,
            resolver=HttpChannelResolver(settings),
            policy=SlaPolicy.from_settings(settings),
            settings=settings,
        )


@dramatiq.actor(max_retries=0)
def scan_sla_timers() -> None:
    """Time_based-движок (E6): откатить просроченные DISPATCHED-заявки на fallback."""
    processed = asyncio.run(_scan_sla_timers())
    _logger.info("sla timers scan: processed=%d", processed)


async def _drain_partner_fallback() -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        return await drain_partner_fallback_batch(
            session,
            resolver=HttpChannelResolver(settings),
            policy=SlaPolicy.from_settings(settings),
            settings=settings,
        )


@dramatiq.actor(max_retries=0)
def drain_outbox_partner_fallback() -> None:
    """Авто-fallback после отклонения партнёром (FR-5.3): передиспетчеризация."""
    processed = asyncio.run(_drain_partner_fallback())
    _logger.info("outbox partner_fallback drain: processed=%d", processed)


async def _run_retention() -> int:
    settings = get_settings()
    async with async_session_factory() as session:
        return await anonymize_expired_raw_input(session, settings=settings)


@dramatiq.actor(max_retries=0)
def run_retention() -> None:
    """Ретенция ПДн (NFR-12): обезличить просроченный raw_input."""
    processed = asyncio.run(_run_retention())
    _logger.info("retention anonymize: processed=%d", processed)


async def _poll_email_inbound() -> int:
    settings = get_settings()
    # Сетевой IMAP-fetch блокирующий → в тред; обработка писем — в БД-сессии.
    messages = await asyncio.to_thread(ImaplibFetcher(settings).fetch_unseen)
    processed = 0
    policy = SlaPolicy.from_settings(settings)
    for message in messages:
        async with async_session_factory() as session:
            await EmailInboundService(session, policy=policy).handle(message)
            processed += 1
    return processed


@dramatiq.actor(max_retries=0)
def poll_email_inbound() -> None:
    """IMAP-опрос входящих ответов партнёра по email (E5). Инертно без imap_host."""
    processed = asyncio.run(_poll_email_inbound())
    _logger.info("email inbound poll: processed=%d", processed)
