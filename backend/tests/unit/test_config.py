"""Тесты настроек (config): дефолты и кеширование."""

from __future__ import annotations

from api.config import Settings, get_settings


def test_defaults() -> None:
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert "5434" in s.database_url  # порт kb-partners (не конфликтует с rehome/kb-support)
    assert s.auth_algorithms == ["RS256"]
    assert s.auth_audience == ""  # пусто на дефолте; в деплое = kb-partners
    assert s.worker_broker_url == ""  # пусто → StubBroker


def test_get_settings_cached() -> None:
    assert get_settings() is get_settings()
