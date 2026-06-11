"""Интерфейс platform-клиента реестра партнёров (E3, FR-3.1).

Потребитель (matcher, M2.3) зависит от этого Protocol и DTO, не от HTTP-реализации
или провизорной формы. При недоступности соседа метод возвращает пустой список
(graceful degradation, NFR-9) — matcher тогда формирует пустую цепочку → NEEDS_REVIEW.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.platform.models import CollaboratorCandidate


@runtime_checkable
class PlatformClient(Protocol):
    async def search_candidates(
        self, *, category: str, service_area: str | None = None
    ) -> list[CollaboratorCandidate]:
        """Кандидаты-партнёры реестра по категории (+ гео). `[]` при недоступности."""
        ...
