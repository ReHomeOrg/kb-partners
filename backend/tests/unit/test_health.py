"""Smoke-тесты инфраструктурных эндпоинтов (M0): healthz/readyz/metrics."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession


def test_healthz_ok(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthz_echoes_request_id(client: TestClient) -> None:
    resp = client.get("/healthz", headers={"X-Request-Id": "req-123"})
    assert resp.headers["x-request-id"] == "req-123"


def test_readyz_503_when_database_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Недоступность БД симулируется детерминированно (не полагаемся на отсутствие
    # БД в окружении: в CI и при integration-тестах Postgres поднят). Падение
    # SELECT 1 → 503; мягкая деградация Redis не достигается — БД обязательна.
    async def _unreachable(_session: AsyncSession) -> None:
        raise RuntimeError("database unreachable")

    monkeypatch.setattr("api.main.check_database", _unreachable)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "unavailable"


def test_metrics_exposed(client: TestClient) -> None:
    # Дёрнем healthz, чтобы счётчик инкрементнулся, затем проверим экспозицию.
    client.get("/healthz")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "http_requests_total" in resp.text
