"""HTTP-роутер конфигураций каналов (§11.2). Монтируется под /api/v1/partners (admin)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, status

from api.channels.dependencies import get_channel_service, require_staff_admin
from api.channels.schemas import ChannelConfigCreate, ChannelConfigRead, ChannelConfigUpdate
from api.channels.service import ChannelConfigService

# Все операции требуют admin-скоуп (зависимость на уровне роутера).
router = APIRouter(
    prefix="/channels", tags=["Channels"], dependencies=[Depends(require_staff_admin)]
)


@router.get("", response_model=list[ChannelConfigRead], summary="Список каналов")
async def list_channels(
    service: ChannelConfigService = Depends(get_channel_service),
    collaborator_id: str | None = Query(default=None),
) -> list[ChannelConfigRead]:
    configs = await service.list_configs(collaborator_id=collaborator_id)
    return [ChannelConfigRead.model_validate(c) for c in configs]


@router.post(
    "",
    response_model=ChannelConfigRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать конфигурацию канала",
)
async def create_channel(
    body: ChannelConfigCreate,
    service: ChannelConfigService = Depends(get_channel_service),
) -> ChannelConfigRead:
    config = await service.create(body)
    return ChannelConfigRead.model_validate(config)


@router.get("/{config_id}", response_model=ChannelConfigRead, summary="Карточка канала")
async def get_channel(
    config_id: uuid.UUID,
    service: ChannelConfigService = Depends(get_channel_service),
) -> ChannelConfigRead:
    config = await service.get_or_404(config_id)
    return ChannelConfigRead.model_validate(config)


@router.patch("/{config_id}", response_model=ChannelConfigRead, summary="Изменить канал")
async def update_channel(
    config_id: uuid.UUID,
    body: ChannelConfigUpdate,
    service: ChannelConfigService = Depends(get_channel_service),
) -> ChannelConfigRead:
    config = await service.update(config_id, body)
    return ChannelConfigRead.model_validate(config)
