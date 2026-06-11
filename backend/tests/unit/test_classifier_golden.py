"""Golden-eval классификатора (E2, §16.13): точность rules-пути на стартовом наборе.

Гейт качества: на детерминированном rules-пути (без LLM) точность по golden-набору
должна быть ≥ целевого порога. Набор — `tests/golden/classifier_golden.json` (владелец/
расширение — Архитектор/kb-eval). Боевой LLM (YandexGPT) проверяется отдельно (mock).
"""

from __future__ import annotations

import json
import pathlib

from api.classifier.engine import ClassifierEngine
from api.classifier.provider import NullLLMProvider
from api.requests.enums import Category

# Целевой порог точности (дефолт; уточняется Архитектором — §16.13).
_TARGET_ACCURACY = 0.8

_GOLDEN_PATH = pathlib.Path(__file__).resolve().parents[1] / "golden" / "classifier_golden.json"


def _load_cases() -> list[tuple[str, Category]]:
    data = json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))
    return [(c["text"], Category(c["category"])) for c in data["cases"]]


async def test_rules_path_accuracy_meets_target() -> None:
    engine = ClassifierEngine(NullLLMProvider())  # rules-only (без сети/LLM)
    cases = _load_cases()
    assert cases, "golden-набор пуст"
    correct = 0
    for text, expected in cases:
        outcome = await engine.classify(text)
        if outcome.category is expected:
            correct += 1
    accuracy = correct / len(cases)
    assert accuracy >= _TARGET_ACCURACY, f"accuracy={accuracy:.2f} < target={_TARGET_ACCURACY}"
