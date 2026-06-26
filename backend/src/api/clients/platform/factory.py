"""Выбор реализации `PlatformClient` по конфигурации.

`KBP_PLATFORM_TEST_FIXTURES=true` → `FixturePlatformClient` (dev/test, реестр из
встроенных тест-партнёров); иначе — боевой `HttpPlatformClient` к kb-platform.
Один шов на все места сборки клиента (dependencies, actors) — без дублирования гейта.
"""

from __future__ import annotations

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.cache import Cache
from api.clients.platform.adapter import HttpPlatformClient
from api.clients.platform.fixture_client import FixturePlatformClient
from api.clients.platform.protocol import PlatformClient
from api.config import Settings


def build_platform_client(
    *,
    settings: Settings,
    http_client: ResilientHttpClient,
    token_provider: TokenProvider,
    cache: Cache,
    cache_ttl_seconds: int,
) -> PlatformClient:
    """`FixturePlatformClient` при включённых тест-фикстурах, иначе `HttpPlatformClient`."""
    if settings.platform_test_fixtures:
        return FixturePlatformClient()
    return HttpPlatformClient(
        http_client=http_client,
        token_provider=token_provider,
        cache=cache,
        cache_ttl_seconds=cache_ttl_seconds,
    )
