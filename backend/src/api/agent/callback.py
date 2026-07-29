"""Эмиссия колбэка смены статуса в Консьерж (E9, U3, issue #7). Без ПДн в payload.

Вызывается из `apply_transition` рядом с webhooks/notifications — в ОДНОЙ транзакции с
переходом FSM (durable, NFR-8). Доставка — после commit воркером (`drainer`).

Три гейта (реш. Архитектора + ревью плана):
1. `concierge_api_base_url` пуст → колбэк выключен (outbox-строки не плодятся);
2. заявка не из AI-чата (нет `chat_session_id` в `source_ref`) → пропуск;
3. статус не «значимый» (нет в `_STATUS_TEXT`) → пропуск — промежуточные технические
   рёбра (CLASSIFYING/MATCHING/...) НЕ уведомляют, чтобы не спамить чат (за один HTTP-
   запрос `apply_transition` может вызываться несколько раз).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.outbox.repository import OutboxRepository
from api.requests.enums import RequestStatus

CONCIERGE_CALLBACK_KIND = "concierge_status"

# Значимые (пользовательские) статусы → шаблон RU-текста. Членство в карте = «значимый»
# (реш. Архитектора «только значимые»). Текст без ПДн: только номер заявки + статус.
_STATUS_TEXT: dict[RequestStatus, str] = {
    RequestStatus.ASSIGNED: "По заявке {number} назначен исполнитель.",
    RequestStatus.DISPATCHED: "Заявка {number} передана исполнителю.",
    RequestStatus.FAILED_DISPATCH: (
        "Заявку {number} не удалось передать исполнителю — подключаем оператора."
    ),
    RequestStatus.ACCEPTED: "Исполнитель принял заявку {number} в работу.",
    RequestStatus.IN_PROGRESS: "По заявке {number} начаты работы.",
    RequestStatus.DONE: "Работы по заявке {number} завершены — подтвердите приёмку.",
    RequestStatus.ACCEPTED_BY_USER: "Приёмка по заявке {number} подтверждена.",
    RequestStatus.DISPUTE: "По заявке {number} открыт спор.",
    RequestStatus.PAID: "Оплата по заявке {number} проведена.",
    RequestStatus.CANCELLED: "Заявка {number} отменена.",
    RequestStatus.REJECTED: "Заявка {number} отклонена.",
}


def status_text(status: RequestStatus, number: str) -> str | None:
    """Нейтральный RU-текст для значимого статуса, иначе `None` (незначимый → не шлём)."""
    template = _STATUS_TEXT.get(status)
    return template.format(number=number) if template is not None else None


def emit_concierge_status_update(
    session: AsyncSession,
    *,
    request_id: uuid.UUID,
    number: str,
    status: RequestStatus,
    source_ref: dict[str, Any] | None,
) -> None:
    """Поставить колбэк смены статуса в outbox (если включён, заявка из чата, статус значим).

    Payload — без ПДн: `session_id` Консьержа, нейтральный `text`, `ref`=номер, `status`,
    `request_id` (для Idempotency-Key на дрейне). `raw_input`/ПДн наружу НЕ уходят.
    """
    if not get_settings().concierge_api_base_url:
        return
    session_id = (source_ref or {}).get("chat_session_id")
    if not session_id:
        return  # заявка не из AI-чата Консьержа — уведомлять некого
    text = status_text(status, number)
    if text is None:
        return  # незначимый (технический) статус — не спамим чат
    OutboxRepository(session).enqueue(
        CONCIERGE_CALLBACK_KIND,
        {
            "session_id": str(session_id),
            "text": text,
            "ref": number,
            "status": status.value,
            "request_id": str(request_id),
        },
    )
