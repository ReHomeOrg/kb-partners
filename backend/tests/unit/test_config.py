"""Тесты настроек (config): дефолты и кеширование."""

from __future__ import annotations

import pytest

from api.config import Settings, get_settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Дефолты читаются из окружения, а KBP_DATABASE_URL задан и в CI, и локально —
    # без снятия тест проверял бы не дефолт, а то, что в env, и падал на любом
    # стенде с непустой переменной.
    monkeypatch.delenv("KBP_DATABASE_URL", raising=False)
    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert "5434" in s.database_url  # порт kb-partners (не конфликтует с rehome/kb-support)
    assert s.auth_algorithms == ["RS256"]
    assert s.auth_audience == ""  # пусто на дефолте; в деплое = kb-partners
    assert s.worker_broker_url == ""  # пусто → StubBroker


def test_get_settings_cached() -> None:
    assert get_settings() is get_settings()
