"""Эмиссия уведомлений в outbox (E8, FR-8.1/8.2). ПДн в payload не кладём.

Вызывается из `apply_transition` рядом с эмиссией webhooks — в ОДНОЙ транзакции с
переходом FSM (durable, NFR-8). Доставка — после commit воркером (`drainer`).
Инертно, пока `notifications_enabled=False` (дефолт): outbox-строки не плодятся.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.notifications.events import notifications_for
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus

NOTIFICATION_KIND = "notification"


def emit_notifications(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    number: str,
    status: RequestStatus,
) -> None:
    """Поставить уведомления о входе заявки в `status` (если уведомления включены).

    Одно outbox-сообщение на адресата (заявитель/партнёр/оператор), payload — без
    ПДн: id/номер заявки, статус, адресат-роль, нейтральная RU-сводка.
    """
    if not get_settings().notifications_enabled:
        return
    repo = OutboxRepository(session)
    for notification in notifications_for(status):
        repo.enqueue(
            NOTIFICATION_KIND,
            {
                "audience": notification.audience.value,
                "request_id": str(request_id),
                "number": number,
                "status": status.value,
                "summary": notification.summary,
            },
        )
