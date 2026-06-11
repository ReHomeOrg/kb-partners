"""FastAPI-зависимости каналов: admin-гейт и фабрика сервиса."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.channels.dispatch import DispatchService
from api.channels.resolver import HttpChannelResolver
from api.channels.service import ChannelConfigService
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException


async def require_staff_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Требовать админ-скоуп (настройка каналов/правил/SLA, §11.2). Иначе 403."""
    if not principal.is_staff_admin:
        raise ProblemException.forbidden(detail="Staff admin scope required")
    return principal


def get_channel_service(session: AsyncSession = Depends(get_session)) -> ChannelConfigService:
    return ChannelConfigService(session)


def get_dispatch_service(session: AsyncSession = Depends(get_session)) -> DispatchService:
    """Сервис диспетчеризации (E4): резолвер каналов из конфигурации."""
    return DispatchService(session, HttpChannelResolver(get_settings()))
