"""Маршрутизация уведомлений по статусу заявки (E8, FR-8.1/8.2).

Чистая таблица «статус FSM → кому и с какой нейтральной RU-сводкой сообщить».
Сводка — БЕЗ ПДн (только смысл события). Один статус может уведомлять нескольких
адресатов (напр. отмена → и партнёру, и заявителю).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from api.requests.enums import RequestStatus


class NotifyAudience(str, enum.Enum):
    """Адресат уведомления (определяет, чей контакт резолвит seam-доставка)."""

    USER = "user"  # заявитель
    PARTNER = "partner"  # назначенный партнёр
    OPERATOR = "operator"  # оператор (эскалация human-handoff)


@dataclass(frozen=True)
class Notification:
    """Решение «уведомить адресата» с нейтральной сводкой (без ПДн)."""

    audience: NotifyAudience
    summary: str


# FR-8.1 — заявителю: принято / партнёр назначен / выезд / выполнено / нужна приёмка.
_USER: dict[RequestStatus, str] = {
    RequestStatus.NEW: "Заявка принята в работу",
    RequestStatus.ASSIGNED: "Партнёр назначен",
    RequestStatus.ACCEPTED: "Партнёр принял заявку",
    RequestStatus.IN_PROGRESS: "Исполнитель приступил к работе",
    RequestStatus.DONE: "Работа выполнена — подтвердите приёмку",
    RequestStatus.CANCELLED: "Заявка отменена",
}

# FR-8.2 — партнёру: новая заявка / изменение / отмена.
_PARTNER: dict[RequestStatus, str] = {
    RequestStatus.DISPATCHED: "Новая заявка вам назначена",
    RequestStatus.CANCELLED: "Заявка отменена",
}

# Эскалация оператору (human-handoff, FR-4.5/9.4) — служит и time_based-движку (E6).
_OPERATOR: dict[RequestStatus, str] = {
    RequestStatus.NEEDS_REVIEW: "Заявка требует ревью оператора",
    RequestStatus.FAILED_DISPATCH: "Не удалось назначить партнёра — нужен оператор",
}


def notifications_for(status: RequestStatus) -> list[Notification]:
    """Кого и с какой сводкой уведомить при входе заявки в `status` (без ПДн)."""
    result: list[Notification] = []
    for audience, table in (
        (NotifyAudience.USER, _USER),
        (NotifyAudience.PARTNER, _PARTNER),
        (NotifyAudience.OPERATOR, _OPERATOR),
    ):
        summary = table.get(status)
        if summary is not None:
            result.append(Notification(audience=audience, summary=summary))
    return result
