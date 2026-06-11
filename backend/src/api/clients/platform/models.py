"""Доменные DTO реестра партнёров (E3, FR-3.1).

НАШИ модели, независимые от провизорной формы kb-platform API. Маппинг
провизорный JSON → эти DTO живёт в `adapter.py` (ADR-0002): смена upstream-контракта
правит только адаптер, не эти типы и не matcher (M2.3).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceOrderRef:
    """Ссылка на заказ `ServiceOrder` в kb-platform (E3, FR-3.5, ADR-0002).

    Заказ остаётся в kb-platform; kb-partners хранит только ссылку (`id`) и
    наблюдаемый статус. Деньги/escrow считает платёжный контур, не модуль.
    """

    id: str
    status: str


@dataclass(frozen=True)
class CollaboratorCandidate:
    """Кандидат-партнёр для подбора (FR-3.1). Поля — то, что нужно ранжированию.

    `id` — `collaborator_id` (строковая ссылка, не локальный FK — арх-константа).
    `channels` — типы доступных каналов доставки (готовность канала, FR-3.1/FR-4.1).
    """

    id: str
    name: str
    category: str
    is_active: bool
    available: bool
    rating: float | None = None
    service_areas: tuple[str, ...] = ()
    channels: tuple[str, ...] = ()
