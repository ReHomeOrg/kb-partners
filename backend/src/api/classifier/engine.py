"""Движок классификации: детерминированные правила + LLM (FR-2.1–FR-2.3, FR-2.6).

Сначала — быстрый путь по ключевым словам: при ОДНОЗНАЧНОМ совпадении категория
определяется без LLM (FR-2.2). При неоднозначности/отсутствии совпадений зовётся
`LLMProvider`; если он инертен (Null) — возвращается результат с низкой
уверенностью (→ `NEEDS_REVIEW` по порогу на сервисном слое, FR-2.4).

Вход — только маскированный текст (ПДн уже вырезаны при приёме, FR-1.6).
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any

from api.classifier.provider import LLMProvider
from api.requests.enums import Category

#: Версия набора правил (трассируемость, FR-2.6). Меняется при правке ключевых слов.
RULES_VERSION = "1.0"
_RULES_MODEL = "rules"
_RULES_CONFIDENCE = 0.9
_AMBIGUOUS_CONFIDENCE = 0.4

# Ключевые слова (стеммы, lower-case) по категориям группы B (ADR-0002).
_KEYWORDS: dict[Category, tuple[str, ...]] = {
    Category.CLEANING: ("убор", "клининг", "помыть", "помой", "чистк", "мойка окон"),
    Category.MOVING: ("переезд", "перевоз", "перевез", "грузчик", "вывез", "погрузк"),
    Category.REPAIR: (
        "ремонт",
        "почин",
        "сантехник",
        "электрик",
        "кран",
        "протечк",
        "розетк",
        "смесител",
    ),
    Category.KEY_DELIVERY: ("ключ", "доставка ключ", "передать ключ"),
}

_AREA_RE = re.compile(r"(\d+)\s*(?:м2|м²|кв\.?\s*м)", re.IGNORECASE)


@dataclass(frozen=True)
class ClassificationOutcome:
    """Результат классификации (трассируемый). Сериализуется в `classification` (§6.1)."""

    category: Category
    confidence: float
    method: str  # "rules" | "llm"
    model: str
    version: str
    product_code: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_classification(self, classified_at: datetime.datetime) -> dict[str, Any]:
        """JSON-вид для поля `classification` (§6.1: confidence/model/version/params/...)."""
        return {
            "confidence": self.confidence,
            "model": self.model,
            "version": self.version,
            "method": self.method,
            "params": self.params,
            "classified_at": classified_at.isoformat(),
        }


def _rule_scores(masked_text: str) -> dict[Category, int]:
    """Число попаданий ключевых слов по категориям (регистронезависимо)."""
    text = masked_text.lower()
    return {
        category: sum(text.count(keyword) for keyword in keywords)
        for category, keywords in _KEYWORDS.items()
    }


def _extract_params(masked_text: str) -> dict[str, Any]:
    """Лёгкое извлечение структурированных параметров (FR-2.1): площадь."""
    params: dict[str, Any] = {}
    area_match = _AREA_RE.search(masked_text)
    if area_match is not None:
        params["area_sqm"] = int(area_match.group(1))
    return params


class ClassifierEngine:
    """Оркестрация rules → LLM. Сервисный слой решает routing по порогу уверенности."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def classify(self, masked_text: str) -> ClassificationOutcome:
        scores = _rule_scores(masked_text)
        matched = [category for category, hits in scores.items() if hits > 0]
        params = _extract_params(masked_text)

        # Быстрый путь: однозначное совпадение → без LLM (FR-2.2).
        if len(matched) == 1:
            return ClassificationOutcome(
                category=matched[0],
                confidence=_RULES_CONFIDENCE,
                method="rules",
                model=_RULES_MODEL,
                version=RULES_VERSION,
                params=params,
            )

        # Неоднозначность/нет совпадений → LLM (FR-2.3).
        llm = await self._provider.classify(masked_text)
        if llm is not None:
            return ClassificationOutcome(
                category=llm.category,
                confidence=llm.confidence,
                method="llm",
                model=llm.model,
                version=llm.version,
                product_code=llm.product_code,
                params={**params, **llm.params},
            )

        # LLM инертен: вернуть низкоуверенный результат → NEEDS_REVIEW (FR-2.4).
        if matched:
            best = max(matched, key=lambda category: scores[category])
            return ClassificationOutcome(
                category=best,
                confidence=_AMBIGUOUS_CONFIDENCE,
                method="rules",
                model=_RULES_MODEL,
                version=RULES_VERSION,
                params=params,
            )
        return ClassificationOutcome(
            category=Category.OTHER,
            confidence=0.0,
            method="rules",
            model=_RULES_MODEL,
            version=RULES_VERSION,
            params=params,
        )
