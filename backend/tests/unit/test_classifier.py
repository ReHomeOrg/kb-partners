"""Юнит-тесты движка классификации (E2): rules-путь, params, LLM-fallback."""

from __future__ import annotations

import datetime

from api.classifier.engine import RULES_VERSION, ClassificationOutcome, ClassifierEngine
from api.classifier.provider import LLMClassification, NullLLMProvider, build_llm_provider
from api.requests.enums import Category

_ENGINE = ClassifierEngine(NullLLMProvider())


async def test_single_keyword_uses_rules_path() -> None:
    out = await _ENGINE.classify("Нужна уборка квартиры")
    assert out.category is Category.CLEANING
    assert out.method == "rules"
    assert out.confidence >= 0.9
    assert out.model == "rules"
    assert out.version == RULES_VERSION


async def test_moving_keyword() -> None:
    out = await _ENGINE.classify("Срочный переезд в субботу")
    assert out.category is Category.MOVING
    assert out.method == "rules"


async def test_no_keywords_returns_other_zero_confidence() -> None:
    out = await _ENGINE.classify("просто текст без смысла")
    assert out.category is Category.OTHER
    assert out.confidence == 0.0


async def test_ambiguous_without_llm_low_confidence() -> None:
    # Две категории сразу + инертный LLM → низкая уверенность (→ NEEDS_REVIEW).
    out = await _ENGINE.classify("нужен переезд и уборка")
    assert out.method == "rules"
    assert out.confidence < 0.7
    assert out.category in {Category.MOVING, Category.CLEANING}


async def test_param_extraction_area() -> None:
    out = await _ENGINE.classify("уборка квартиры 50 м2")
    assert out.params["area_sqm"] == 50


async def test_llm_path_used_when_ambiguous() -> None:
    class _FakeProvider:
        async def classify(self, masked_text: str) -> LLMClassification:
            return LLMClassification(
                category=Category.REPAIR,
                confidence=0.88,
                model="fake-llm",
                version="v1",
                params={"detail": "x"},
            )

    out = await ClassifierEngine(_FakeProvider()).classify("переезд и уборка")
    assert out.method == "llm"
    assert out.category is Category.REPAIR
    assert out.model == "fake-llm"
    assert out.params["detail"] == "x"


async def test_null_provider_returns_none() -> None:
    assert await NullLLMProvider().classify("что-то") is None


def test_build_provider_is_null_until_adr() -> None:
    # Реальные SDK подключаются отдельным ADR; пока любой выбор → NullLLMProvider.
    assert isinstance(build_llm_provider("yandexgpt"), NullLLMProvider)


def test_outcome_serialization_has_trace_fields() -> None:
    out = ClassificationOutcome(
        category=Category.CLEANING,
        confidence=0.9,
        method="rules",
        model="rules",
        version=RULES_VERSION,
    )
    payload = out.to_classification(datetime.datetime(2026, 6, 11, tzinfo=datetime.UTC))
    assert payload["confidence"] == 0.9
    assert payload["method"] == "rules"
    assert payload["model"] == "rules"
    assert payload["version"] == RULES_VERSION
    assert "classified_at" in payload
    assert payload["params"] == {}
