"""Доступ к хранилищу конфигураций каналов (своя БД, арх-константа)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.enums import ChannelRole
from api.channels.models import (
    DispatchAttempt,
    InboundEvent,
    PartnerChannelConfig,
)


class InboundRepository:
    """Доступ к каналам по inbound-токену и журналу входящих (дедуп, E5)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def config_by_inbound_token(self, token: str) -> PartnerChannelConfig | None:
        stmt = select(PartnerChannelConfig).where(PartnerChannelConfig.inbound_token == token)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def is_seen(self, channel_config_id: uuid.UUID, nonce: str) -> bool:
        stmt = select(InboundEvent.id).where(
            InboundEvent.channel_config_id == channel_config_id,
            InboundEvent.nonce == nonce,
        )
        return (await self._session.execute(stmt)).first() is not None

    def add_event(self, event: InboundEvent) -> None:
        self._session.add(event)


class DispatchRepository:
    """Доступ к попыткам диспетчеризации и активным каналам партнёра (E4)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active_channels_for(self, collaborator_id: str) -> list[PartnerChannelConfig]:
        """Активные ОСНОВНЫЕ каналы партнёра по приоритету (§9.3).

        Каналы-копии (`role=DUPLICATE`, ADR-0006) в переборе фолбэка не участвуют: они
        не «запасной вариант», а дополнительная доставка после успешной основной. Иначе
        копия могла бы стать единственной доставкой — партнёр получил бы письмо вместо
        заявки в CRM, а диспетч счёл бы это успехом.
        """
        stmt = (
            select(PartnerChannelConfig)
            .where(
                PartnerChannelConfig.collaborator_id == collaborator_id,
                PartnerChannelConfig.is_active.is_(True),
                PartnerChannelConfig.role == ChannelRole.PRIMARY,
            )
            .order_by(PartnerChannelConfig.priority.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def duplicate_channels_for(self, collaborator_id: str) -> list[PartnerChannelConfig]:
        """Активные каналы-копии партнёра (ADR-0006), в порядке приоритета."""
        stmt = (
            select(PartnerChannelConfig)
            .where(
                PartnerChannelConfig.collaborator_id == collaborator_id,
                PartnerChannelConfig.is_active.is_(True),
                PartnerChannelConfig.role == ChannelRole.DUPLICATE,
            )
            .order_by(PartnerChannelConfig.priority.asc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def count_attempts(self, request_id: uuid.UUID) -> int:
        stmt = (
            select(func.count())
            .select_from(DispatchAttempt)
            .where(DispatchAttempt.request_id == request_id)
        )
        return int((await self._session.execute(stmt)).scalar_one())

    def add_attempt(self, attempt: DispatchAttempt) -> None:
        self._session.add(attempt)


class ChannelConfigRepository:
    """Репозиторий `PartnerChannelConfig`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, config: PartnerChannelConfig) -> None:
        self._session.add(config)

    async def get(self, config_id: uuid.UUID) -> PartnerChannelConfig | None:
        stmt = select(PartnerChannelConfig).where(PartnerChannelConfig.id == config_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_configs(
        self, *, collaborator_id: str | None = None
    ) -> list[PartnerChannelConfig]:
        stmt = select(PartnerChannelConfig)
        if collaborator_id is not None:
            stmt = stmt.where(PartnerChannelConfig.collaborator_id == collaborator_id)
        stmt = stmt.order_by(
            PartnerChannelConfig.collaborator_id.asc(), PartnerChannelConfig.priority.asc()
        )
        return list((await self._session.execute(stmt)).scalars().all())
