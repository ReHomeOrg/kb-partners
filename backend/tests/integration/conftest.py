"""Общие фикстуры интеграционных тестов заявок (real DB, dev-порт 5434).

Изоляция — внешняя транзакция на соединении + `join_transaction_mode=
"create_savepoint"`: коммиты сервиса уходят в SAVEPOINT, внешний rollback в
teardown откатывает всё (последовательность номеров не транзакционна и не
сбрасывается — тесты проверяют формат `RQ-`, не конкретное значение).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal, PrincipalKind
from api.config import get_settings
from api.db import get_session
from api.main import app
from api.requests.enums import AccessLevel, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest


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


@pytest.fixture
def make_principal() -> Callable[..., Principal]:
    """Фабрика `Principal` со случайным user_id."""

    def _make(kind: PrincipalKind, **kwargs: Any) -> Principal:
        return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)

    return _make


@pytest_asyncio.fixture
def seed(session: AsyncSession) -> Callable[..., Awaitable[ServiceRequest]]:
    """Фабрика заявок в тест-сессии (savepoint). Возвращает сохранённый `ServiceRequest`."""

    async def _seed(
        *,
        requester_id: str = "u-owner",
        partner_id: str | None = None,
        status: RequestStatus = RequestStatus.NEW,
        access_level: AccessLevel = AccessLevel.LOGGED,
        raw_input: str = "Реальный текст заявки",
        raw_input_masked: str = "Маскированный текст",
    ) -> ServiceRequest:
        request = ServiceRequest(
            number=f"RQ-T-{uuid.uuid4().hex[:10]}",
            requester_id=requester_id,
            channel_in=ChannelIn.WEB_FORM,
            raw_input=raw_input,
            raw_input_masked=raw_input_masked,
            status=status,
            access_level=access_level,
            partner_id=partner_id,
            custom_fields={},
        )
        session.add(request)
        await session.commit()
        return request

    return _seed
