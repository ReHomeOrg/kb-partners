"""FastAPI-зависимости каналов: admin-гейт и фабрика сервиса."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.dependencies import get_current_principal
from api.auth.principal import Principal
from api.channels.dispatch import DispatchService
from api.channels.inbound import InboundService
from api.channels.resolver import HttpChannelResolver
from api.channels.service import ChannelConfigService
from api.config import get_settings
from api.db import get_session
from api.errors import ProblemException
from api.sla.engine import SlaPolicy


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
    """Сервис диспетчеризации (E4): резолвер каналов + SLA-политика из конфигурации."""
    settings = get_settings()
    return DispatchService(
        session, HttpChannelResolver(settings), SlaPolicy.from_settings(settings)
    )


def get_inbound_service(session: AsyncSession = Depends(get_session)) -> InboundService:
    """Сервис приёма входящих от партнёров (E5) + SLA-политика."""
    return InboundService(session, policy=SlaPolicy.from_settings(get_settings()))
