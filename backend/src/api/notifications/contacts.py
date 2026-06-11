"""Резолв контакта адресата уведомления на дрейне (E8, ФЗ-152).

Контакт (телефон/email — ПДн) НЕ хранится в outbox: резолвится в момент доставки по
непрозрачным ссылкам из payload. Заявитель → rehome.one (get_requester_context),
партнёр → kb-platform (get_partner_contact), оператор → адрес из конфига. Недоступность
соседа → пустой контакт (каналы пропускаются, без падения). Контакт в логи не пишем.
"""

from __future__ import annotations

from typing import Protocol

from api.clients.platform.protocol import PlatformClient
from api.clients.rehome.protocol import RehomeOneClient
from api.config import Settings
from api.notifications.channels import NotificationNotice, Recipient
from api.notifications.events import NotifyAudience


class ContactResolver(Protocol):
    async def resolve(self, notice: NotificationNotice) -> Recipient: ...


class NeighborContactResolver:
    """Резолвер контактов через соседей (rehome.one / kb-platform) + конфиг оператора."""

    def __init__(
        self, *, rehome: RehomeOneClient, platform: PlatformClient, settings: Settings
    ) -> None:
        self._rehome = rehome
        self._platform = platform
        self._settings = settings

    async def resolve(self, notice: NotificationNotice) -> Recipient:
        if notice.audience is NotifyAudience.USER and notice.requester_id:
            context = await self._rehome.get_requester_context(
                requester_id=notice.requester_id, premises_id=None, booking_id=None
            )
            if context is not None:
                return Recipient(phone=context.user_phone, email=context.user_email)
            return Recipient()
        if notice.audience is NotifyAudience.PARTNER and notice.partner_id:
            contact = await self._platform.get_partner_contact(partner_id=notice.partner_id)
            if contact is not None:
                return Recipient(phone=contact.phone, email=contact.email)
            return Recipient()
        if notice.audience is NotifyAudience.OPERATOR:
            return Recipient(email=self._settings.notify_operator_email or None)
        return Recipient()


class NullContactResolver:
    """Резолвер-заглушка (контакт неизвестен) — все каналы пропускаются."""

    async def resolve(self, notice: NotificationNotice) -> Recipient:
        return Recipient()
