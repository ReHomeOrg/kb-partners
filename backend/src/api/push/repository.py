"""Доступ к хранилищу web-push подписок (E8, ADR-0004)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.push.models import PushSubscription


class PushSubscriptionRepository:
    """Репозиторий подписок: upsert по (owner_id, endpoint), список владельца, удаление."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, owner_id: str, audience: str, endpoint: str, p256dh: str, auth: str
    ) -> None:
        """Идемпотентно сохранить подписку (повтор регистрации обновляет ключи)."""
        stmt = insert(PushSubscription).values(
            owner_id=owner_id, audience=audience, endpoint=endpoint, p256dh=p256dh, auth=auth
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[PushSubscription.owner_id, PushSubscription.endpoint],
            set_={"p256dh": p256dh, "auth": auth, "audience": audience},
        )
        await self._session.execute(stmt)

    async def list_for_owner(self, owner_id: str) -> list[PushSubscription]:
        stmt = select(PushSubscription).where(PushSubscription.owner_id == owner_id)
        return list((await self._session.execute(stmt)).scalars().all())

    async def delete(self, *, owner_id: str, endpoint: str) -> None:
        await self._session.execute(
            delete(PushSubscription).where(
                PushSubscription.owner_id == owner_id, PushSubscription.endpoint == endpoint
            )
        )
