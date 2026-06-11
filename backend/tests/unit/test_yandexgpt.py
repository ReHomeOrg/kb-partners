"""Юнит-тесты боевого LLM-провайдера YandexGPT (E2, ADR-0003) — без сети (MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from api.classifier.provider import NullLLMProvider
from api.classifier.yandexgpt import YandexGptProvider, build_llm_provider
from api.config import Settings
from api.requests.enums import Category

_CONFIGURED = Settings(
    classifier_llm_provider="yandexgpt", yandexgpt_api_key="k", yandexgpt_folder_id="f"
)


def _completion(text: str, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if status >= 400:
            return httpx.Response(status, json={"error": "x"})
        return httpx.Response(200, json={"result": {"alternatives": [{"message": {"text": text}}]}})

    return httpx.MockTransport(handler)


async def test_parses_strict_json_completion() -> None:
    transport = _completion('{"category": "CLEANING", "confidence": 0.92, "params": {}}')
    provider = YandexGptProvider(_CONFIGURED, transport=transport)
    result = await provider.classify("нужна уборка квартиры")
    assert result is not None
    assert result.category is Category.CLEANING
    assert result.confidence == pytest.approx(0.92)
    assert result.model == "yandexgpt-lite"


async def test_strips_code_fences() -> None:
    transport = _completion('```json\n{"category": "MOVING", "confidence": 0.8}\n```')
    provider = YandexGptProvider(_CONFIGURED, transport=transport)
    result = await provider.classify("переезд")
    assert result is not None
    assert result.category is Category.MOVING


async def test_confidence_clamped() -> None:
    transport = _completion('{"category": "REPAIR", "confidence": 1.5}')
    result = await YandexGptProvider(_CONFIGURED, transport=transport).classify("ремонт")
    assert result is not None and result.confidence == 1.0


async def test_unparseable_completion_degrades_to_none() -> None:
    provider = YandexGptProvider(_CONFIGURED, transport=_completion("это не json"))
    assert await provider.classify("текст") is None


async def test_http_error_degrades_to_none() -> None:
    provider = YandexGptProvider(_CONFIGURED, transport=_completion("{}", status=400))
    assert await provider.classify("текст") is None


async def test_unknown_category_degrades_to_none() -> None:
    transport = _completion('{"category": "FLYING", "confidence": 0.9}')
    assert await YandexGptProvider(_CONFIGURED, transport=transport).classify("x") is None


def test_build_provider_inert_by_default() -> None:
    assert isinstance(build_llm_provider(Settings()), NullLLMProvider)
    # Имя без кредов → тоже инертно (fail-safe).
    assert isinstance(
        build_llm_provider(Settings(classifier_llm_provider="yandexgpt")), NullLLMProvider
    )


def test_build_provider_yandexgpt_when_configured() -> None:
    assert isinstance(build_llm_provider(_CONFIGURED), YandexGptProvider)
