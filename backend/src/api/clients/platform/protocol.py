"""Интерфейс platform-клиента реестра партнёров (E3, FR-3.1).

Потребитель (matcher, M2.3) зависит от этого Protocol и DTO, не от HTTP-реализации
или провизорной формы. При недоступности соседа метод возвращает пустой список
(graceful degradation, NFR-9) — matcher тогда формирует пустую цепочку → NEEDS_REVIEW.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.platform.models import CollaboratorCandidate, PartnerContact, ServiceOrderRef


@runtime_checkable
class PlatformClient(Protocol):
    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        """Кандидаты-партнёры реестра по категории (+ гео). `[]` при недоступности."""
        ...

    async def get_partner_contact(self, *, partner_id: str) -> PartnerContact | None:
        """Контакт партнёра для уведомлений (E8, FR-8.2). `None` при недоступности/4xx."""
        ...

    async def create_service_order(
        self, *, request_id: str, partner_id: str, category: str, idempotency_key: str
    ) -> ServiceOrderRef | None:
        """Создать/привязать ServiceOrder в kb-platform (FR-3.5, идемпотентно по ключу).

        `None` при недоступности соседа (вызывающий решает: повторить/эскалировать).
        """
        ...
