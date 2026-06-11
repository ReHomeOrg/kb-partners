"""Движок ранжирования партнёров (E3, FR-3.1–FR-3.3, §4.5).

Порядок отбора: категория → гео (`service_area`) → доступность → рейтинг →
готовность канала. Возвращает выбранного партнёра, разрешённый канал доставки,
`fallback_chain` (упорядоченные id для авто-fallback) и `match_trace` (объяснимость).
`None` — нет пригодных кандидатов (сервис уводит заявку в human-handoff).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.clients.platform.models import CollaboratorCandidate


@dataclass(frozen=True)
class MatchResult:
    """Итог подбора. `match_trace` — без таймштампа (его добавит сервис)."""

    partner_id: str
    delivery_channel: str
    fallback_chain: list[str]
    match_trace: dict[str, Any]


class Matcher:
    """Ранжирование кандидатов реестра. Чистая логика — без сети/БД (тестируема)."""

    def rank(
        self,
        candidates: list[CollaboratorCandidate],
        *,
        category: str,
        service_area: str | None = None,
    ) -> MatchResult | None:
        eligible = [
            c
            for c in candidates
            if self._is_eligible(c, category=category, service_area=service_area)
        ]
        if not eligible:
            return None
        # Рейтинг по убыванию; tie-break по id для детерминизма.
        ranked = sorted(
            eligible, key=lambda c: (-(c.rating if c.rating is not None else 0.0), c.id)
        )
        chosen = ranked[0]
        trace: dict[str, Any] = {
            "method": "auto",
            "ranked_by": ["category", "geo", "availability", "rating", "channel"],
            "service_area": service_area,
            "candidates": [
                {
                    "id": c.id,
                    "rating": c.rating,
                    "service_areas": list(c.service_areas),
                    "channels": list(c.channels),
                }
                for c in ranked
            ],
        }
        return MatchResult(
            partner_id=chosen.id,
            delivery_channel=chosen.channels[0],
            fallback_chain=[c.id for c in ranked[1:]],
            match_trace=trace,
        )

    @staticmethod
    def _is_eligible(
        candidate: CollaboratorCandidate, *, category: str, service_area: str | None
    ) -> bool:
        if candidate.category != category:
            return False
        if not candidate.is_active or not candidate.available:
            return False
        if not candidate.channels:  # нет готового канала доставки (FR-3.1)
            return False
        # Гео: если запрошен район и у партнёра заданы зоны — он должен покрывать район.
        if service_area is not None and candidate.service_areas:
            return service_area in candidate.service_areas
        return True
