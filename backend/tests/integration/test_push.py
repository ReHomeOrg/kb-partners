"""Интеграционные тесты web-push подписок (E8, FR-10.1): регистрация/отписка + дрейн."""

from __future__ import annotations

from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.push.models import PushSubscription
from api.push.repository import PushSubscriptionRepository

_BASE = "/api/v1/partners/push/subscriptions"


async def _count(session: AsyncSession, owner_id: str) -> int:
    stmt = (
        select(func.count())
        .select_from(PushSubscription)
        .where(PushSubscription.owner_id == owner_id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def test_subscribe_stores_for_owner(
    make_client: Callable[..., AsyncClient],
    make_principal: Callable[..., Principal],
    session: AsyncSession,
) -> None:
    principal = make_principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    body = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
    resp = await client.post(_BASE, json=body)
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"
    assert await _count(session, str(principal.user_id)) == 1


async def test_subscribe_is_idempotent(
    make_client: Callable[..., AsyncClient],
    make_principal: Callable[..., Principal],
    session: AsyncSession,
) -> None:
    principal = make_principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    body = {"endpoint": "https://push.example/same", "keys": {"p256dh": "k1", "auth": "a1"}}
    await client.post(_BASE, json=body)
    body["keys"] = {"p256dh": "k2", "auth": "a2"}  # повтор обновляет ключи
    await client.post(_BASE, json=body)
    assert await _count(session, str(principal.user_id)) == 1


async def test_partner_owner_is_partner_id(
    make_client: Callable[..., AsyncClient],
    make_principal: Callable[..., Principal],
    session: AsyncSession,
) -> None:
    principal = make_principal(PrincipalKind.PARTNER, partner_id="c-9")
    client = make_client(principal)
    body = {"endpoint": "https://push.example/p", "keys": {"p256dh": "k", "auth": "a"}}
    await client.post(_BASE, json=body)
    assert await _count(session, "c-9") == 1
    assert await _count(session, str(principal.user_id)) == 0


async def test_unsubscribe_removes(
    make_client: Callable[..., AsyncClient],
    make_principal: Callable[..., Principal],
    session: AsyncSession,
) -> None:
    principal = make_principal(PrincipalKind.REQUESTER)
    client = make_client(principal)
    body = {"endpoint": "https://push.example/del", "keys": {"p256dh": "k", "auth": "a"}}
    await client.post(_BASE, json=body)
    resp = await client.request("DELETE", _BASE, params={"endpoint": "https://push.example/del"})
    assert resp.status_code == 200
    assert await _count(session, str(principal.user_id)) == 0


async def test_repository_upsert_and_list(session: AsyncSession) -> None:
    repo = PushSubscriptionRepository(session)
    await repo.upsert(owner_id="u-x", audience="user", endpoint="e1", p256dh="k", auth="a")
    await session.commit()
    subs = await repo.list_for_owner("u-x")
    assert len(subs) == 1 and subs[0].endpoint == "e1"
