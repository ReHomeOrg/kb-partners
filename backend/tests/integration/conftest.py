"""Общие фикстуры интеграционных тестов заявок (real DB, dev-порт 5434).

Изоляция — внешняя транзакция на соединении + `join_transaction_mode=
"create_savepoint"`: коммиты сервиса уходят в SAVEPOINT, внешний rollback в
teardown откатывает всё (последовательность номеров не транзакционна и не
сбрасывается — тесты проверяют формат `RQ-`, не конкретное значение).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.config import get_settings
from api.db import get_session
from api.main import app


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    conn = await engine.connect()
    trans = await conn.begin()
    sess = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield sess
    finally:
        await sess.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def make_client(
    session: AsyncSession,
) -> AsyncIterator[Callable[..., AsyncClient]]:
    """Фабрика HTTP-клиентов: `make_client(principal)` инжектит субъекта и тест-сессию."""
    transport = ASGITransport(app=app)
    opened: list[AsyncClient] = []

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    def _make(principal: Principal | None = None) -> AsyncClient:
        if principal is not None:
            app.dependency_overrides[get_current_principal] = lambda: principal
        app.dependency_overrides[get_session] = _session_override
        client = AsyncClient(transport=transport, base_url="http://test")
        opened.append(client)
        return client

    yield _make

    for client in opened:
        await client.aclose()
    app.dependency_overrides.clear()
