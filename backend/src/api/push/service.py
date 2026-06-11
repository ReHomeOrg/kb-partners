"""Сервис web-push подписок (E8, FR-10.1): регистрация/отписка владельцем.

`owner_id`/`audience` вычисляются БЭКЕНДОМ из проверенного принципала (не из тела —
анти-спуф, §12): партнёр → partner_id/'partner', иначе → user_id/'user'. Подписка
видна и управляется только своим владельцем.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal
from api.observability.logging import get_logger
from api.push.repository import PushSubscriptionRepository
from api.push.schemas import PushSubscriptionAck, PushSubscriptionCreate

_logger = get_logger("push.service")


def _owner(principal: Principal) -> tuple[str, str]:
    """(owner_id, audience) из принципала — только бэкендом (анти-спуф)."""
    if principal.is_partner and principal.partner_id is not None:
        return principal.partner_id, "partner"
    return str(principal.user_id), "user"


class PushSubscriptionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = PushSubscriptionRepository(session)

    async def subscribe(
        self, principal: Principal, body: PushSubscriptionCreate
    ) -> PushSubscriptionAck:
        owner_id, audience = _owner(principal)
        await self._repo.upsert(
            owner_id=owner_id,
            audience=audience,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
        )
        await self._session.commit()
        return PushSubscriptionAck(status="subscribed")

    async def unsubscribe(self, principal: Principal, endpoint: str) -> PushSubscriptionAck:
        owner_id, _ = _owner(principal)
        await self._repo.delete(owner_id=owner_id, endpoint=endpoint)
        await self._session.commit()
        return PushSubscriptionAck(status="unsubscribed")
