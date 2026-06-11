"""Контрактные тесты (AT-002) — соответствие реализации docs/openapi.yaml.

На M0 проверяем инфраструктурный контракт: спека парсится, объявляет
инфраструктурные операции, а реальный ответ `/healthz` валиден против схемы
`Healthz` из спецификации. По мере эпиков сюда добавляются доменные операции.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

_OPENAPI_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml"


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    with _OPENAPI_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def test_spec_parses_and_declares_infra(spec: dict[str, Any]) -> None:
    assert spec["openapi"].startswith("3.1")
    for path in ("/healthz", "/readyz", "/metrics"):
        assert path in spec["paths"], f"missing path {path}"


def test_healthz_response_matches_schema(spec: dict[str, Any], client: TestClient) -> None:
    schema = spec["components"]["schemas"]["Healthz"]
    Draft202012Validator.check_schema(schema)
    body = client.get("/healthz").json()
    Draft202012Validator(schema).validate(body)


def test_error_schema_is_valid(spec: dict[str, Any]) -> None:
    schema = spec["components"]["schemas"]["Error"]
    Draft202012Validator.check_schema(schema)
