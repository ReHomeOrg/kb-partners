"""Эмиссия доменных событий в outbox (E8, §11.4). Без ПДн в payload."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus

WEBHOOK_KIND = "webhook"

# Статус FSM → имя доменного события (§11.4). Неперечисленные → request.<status>.
_STATUS_EVENT: dict[RequestStatus, str] = {
    RequestStatus.CLASSIFIED: "request.classified",
    RequestStatus.NEEDS_REVIEW: "request.needs_review",
    RequestStatus.ASSIGNED: "request.assigned",
    RequestStatus.DISPATCHED: "request.dispatched",
    RequestStatus.FAILED_DISPATCH: "request.dispatch_failed",
    RequestStatus.ACCEPTED: "request.accepted_by_partner",
    RequestStatus.IN_PROGRESS: "request.in_progress",
    RequestStatus.DONE: "request.done",
    RequestStatus.ACCEPTED_BY_USER: "request.accepted_by_user",
    RequestStatus.DISPUTE: "request.dispute_opened",
    RequestStatus.PAID: "request.paid",
    RequestStatus.CANCELLED: "request.cancelled",
}


def status_event(status: RequestStatus) -> str:
    return _STATUS_EVENT.get(status, f"request.{status.value.lower()}")


def emit_event(
    session: AsyncSession,
    *,
    event: str,
    request_id: uuid.UUID,
    number: str,
    status: RequestStatus,
) -> None:
    """Поставить событие в outbox (если webhooks включены). Доставка — после commit."""
    if not get_settings().webhook_url:
        return
    OutboxRepository(session).enqueue(
        WEBHOOK_KIND,
        {
            "event": event,
            "request_id": str(request_id),
            "number": number,
            "status": status.value,
        },
    )
