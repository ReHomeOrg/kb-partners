"""Абстракция `LLMProvider` для классификатора (FR-2.3, env-switch как в kb-search).

Реальные провайдеры (YandexGPT/GigaChat/vLLM) подключают внешние SDK и требуют
отдельного ADR (CLAUDE.md правило 6). На M2.1 доступен только `NullLLMProvider`
(LLM-путь инертен → работает детерминированный rules-путь). Контракт зафиксирован,
чтобы подключение провайдера не меняло сервисный слой.

ВАЖНО: `classify` принимает ТОЛЬКО маскированный текст (`raw_input_masked`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from api.requests.enums import Category


@dataclass(frozen=True)
class LLMClassification:
    """Результат LLM-классификации (трассируемый, FR-2.6)."""

    category: Category
    confidence: float
    product_code: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    model: str = "unknown"
    version: str = "unknown"


class LLMProvider(Protocol):
    """Провайдер LLM-классификации по маскированному тексту."""

    async def classify(self, masked_text: str) -> LLMClassification | None:
        """Вернуть классификацию или `None`, если провайдер не дал ответа."""
        ...


class NullLLMProvider:
    """Инертный провайдер (LLM не сконфигурирован): всегда `None` → только rules-путь."""

    async def classify(self, masked_text: str) -> LLMClassification | None:
        return None


# Сборка провайдера по конфигурации — в `api.classifier.yandexgpt.build_llm_provider`
# (там живёт боевой YandexGptProvider; держать фабрику здесь создало бы цикл импорта).
