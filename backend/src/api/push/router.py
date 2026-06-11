"""HTTP-роутер web-push подписок (E8, FR-10.1). Монтируется под /api/v1/partners."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.db import get_session
from api.push.schemas import PushSubscriptionAck, PushSubscriptionCreate
from api.push.service import PushSubscriptionService

router = APIRouter(tags=["push"])


def get_push_service(session: AsyncSession = Depends(get_session)) -> PushSubscriptionService:
    return PushSubscriptionService(session)


@router.post("/push/subscriptions", response_model=PushSubscriptionAck)
async def subscribe(
    body: PushSubscriptionCreate,
    principal: Principal = Depends(get_current_principal),
    service: PushSubscriptionService = Depends(get_push_service),
) -> PushSubscriptionAck:
    """Зарегистрировать подписку браузера на web-push (владелец из токена)."""
    return await service.subscribe(principal, body)


@router.delete("/push/subscriptions", response_model=PushSubscriptionAck)
async def unsubscribe(
    endpoint: str,
    principal: Principal = Depends(get_current_principal),
    service: PushSubscriptionService = Depends(get_push_service),
) -> PushSubscriptionAck:
    """Отписать устройство (по endpoint) — только своего владельца."""
    return await service.unsubscribe(principal, endpoint)
