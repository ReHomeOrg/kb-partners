"""Сервис управления конфигурациями каналов (§11.2, admin)."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.models import PartnerChannelConfig
from api.channels.repository import ChannelConfigRepository
from api.channels.schemas import ChannelConfigCreate, ChannelConfigUpdate
from api.errors import ProblemException


class ChannelConfigService:
    """CRUD конфигураций каналов. Уникальность (collaborator_id, channel_type) → 409."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ChannelConfigRepository(session)

    async def create(self, body: ChannelConfigCreate) -> PartnerChannelConfig:
        config = PartnerChannelConfig(
            collaborator_id=body.collaborator_id,
            channel_type=body.channel_type,
            priority=body.priority,
            config=body.config,
            inbound_token=body.inbound_token,
            is_active=body.is_active,
        )
        self._repo.add(config)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ProblemException.conflict(
                detail="Channel config for this collaborator and type already exists"
            ) from exc
        # Подтянуть server-side значения (created_at/updated_at) в async-контексте,
        # иначе ленивое дочитывание при сериализации упадёт (MissingGreenlet).
        await self._session.refresh(config)
        return config

    async def get_or_404(self, config_id: uuid.UUID) -> PartnerChannelConfig:
        config = await self._repo.get(config_id)
        if config is None:
            raise ProblemException.not_found()
        return config

    async def list_configs(self, *, collaborator_id: str | None) -> list[PartnerChannelConfig]:
        return await self._repo.list_configs(collaborator_id=collaborator_id)

    async def update(self, config_id: uuid.UUID, body: ChannelConfigUpdate) -> PartnerChannelConfig:
        config = await self.get_or_404(config_id)
        if body.priority is not None:
            config.priority = body.priority
        if body.config is not None:
            config.config = body.config
        if body.inbound_token is not None:
            config.inbound_token = body.inbound_token
        if body.is_active is not None:
            config.is_active = body.is_active
        await self._session.commit()
        await self._session.refresh(config)  # server onupdate(updated_at) → reload
        return config
