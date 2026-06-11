"""Боевой LLM-провайдер классификатора — YandexGPT (E2, FR-2.3, ADR-0003).

«Разрабатываем сами»: свой HTTP-адаптер поверх `ResilientHttpClient` (без вендорского
SDK), Api-Key-авторизация, переключение по env. На вход модели идёт ТОЛЬКО
`raw_input_masked` (ПДн вырезаны при приёме, FR-1.6) — текст в логи не пишется.

Деградация (NFR-9): недоступность/4xx/битый ответ → `None` (движок уходит на rules-путь
или NEEDS_REVIEW). Модель просим вернуть строгий JSON {category, confidence, ...};
неразбираемый ответ → `None`. Трассировка (model/version) сохраняется в `classification`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from api.classifier.provider import LLMClassification, LLMProvider, NullLLMProvider
from api.clients.errors import ExternalServiceError
from api.clients.factory import build_resilient_client
from api.config import Settings
from api.observability.logging import get_logger
from api.requests.enums import Category

_logger = get_logger("classifier.yandexgpt")

_COMPLETION_PATH = "/foundationModels/v1/completion"

# Инструкция модели: классификация в категории группы B (ADR-0002) + строгий JSON.
_SYSTEM_PROMPT = (
    "Ты классификатор заявок на бытовые услуги. Определи категорию по тексту заявки. "
    "Категории: CLEANING (уборка/клининг), MOVING (переезд/грузчики), "
    "REPAIR (ремонт/сантехник/электрик), KEY_DELIVERY (доставка/передача ключей), "
    "OTHER (не подходит ни одна). Ответь СТРОГО одним JSON-объектом без пояснений: "
    '{"category": "<КАТЕГОРИЯ>", "confidence": <0..1>, "product_code": null, "params": {}}'
)


class YandexGptProvider:
    """`LLMProvider` поверх YandexGPT Foundation Models API.

    `transport` инъектируется в тестах (httpx.MockTransport) — боевой путь сети не трогает.
    """

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._s = settings
        self._transport = transport

    @property
    def _model_uri(self) -> str:
        return f"gpt://{self._s.yandexgpt_folder_id}/{self._s.yandexgpt_model}/latest"

    def _build_body(self, masked_text: str) -> dict[str, Any]:
        return {
            "modelUri": self._model_uri,
            "completionOptions": {"stream": False, "temperature": 0.0, "maxTokens": 200},
            "messages": [
                {"role": "system", "text": _SYSTEM_PROMPT},
                {"role": "user", "text": masked_text},
            ],
        }

    async def classify(self, masked_text: str) -> LLMClassification | None:
        headers = {
            "Authorization": f"Api-Key {self._s.yandexgpt_api_key}",
            "x-folder-id": self._s.yandexgpt_folder_id,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._s.yandexgpt_api_base_url,
                timeout=self._s.client_timeout_seconds,
                transport=self._transport,
            ) as http:
                client = build_resilient_client("yandexgpt", http, self._s)
                response = await client.request(
                    "POST",
                    _COMPLETION_PATH,
                    operation="classify",
                    headers=headers,
                    json=self._build_body(masked_text),
                )
        except ExternalServiceError as exc:
            _logger.warning("yandexgpt degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("yandexgpt degraded: status=%d", response.status_code)
            return None
        return self._parse(response.json())

    def _parse(self, payload: Any) -> LLMClassification | None:
        """Распарсить ответ YandexGPT → LLMClassification. Любая ошибка формата → None."""
        try:
            alternatives = payload["result"]["alternatives"]
            text = alternatives[0]["message"]["text"]
            data = json.loads(_strip_fences(text))
            category = Category(str(data["category"]).upper())
            confidence = float(data["confidence"])
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            _logger.warning("yandexgpt degraded: unparseable completion")
            return None
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        product = data.get("product_code")
        return LLMClassification(
            category=category,
            confidence=max(0.0, min(1.0, confidence)),
            product_code=str(product) if product else None,
            params=params,
            model=self._s.yandexgpt_model,
            version="v1",
        )


def _strip_fences(text: str) -> str:
    """Убрать ```json ... ``` обёртку, если модель её добавила."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else cleaned
        cleaned = cleaned.removeprefix("json").strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    return cleaned


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Собрать LLM-провайдера по конфигурации (env-switch, ADR-0003).

    `yandexgpt` + заполненные api_key/folder_id → YandexGptProvider; иначе (включая
    пустые креды) — `NullLLMProvider` (rules-only). Прочие имена зарезервированы под
    будущие ADR (gigachat/vllm) и пока резолвятся в Null.
    """
    if (
        settings.classifier_llm_provider == "yandexgpt"
        and settings.yandexgpt_api_key
        and settings.yandexgpt_folder_id
    ):
        return YandexGptProvider(settings)
    return NullLLMProvider()
