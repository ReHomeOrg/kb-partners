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


def test_spec_declares_intake_operations(spec: dict[str, Any]) -> None:
    # E1 intake (M1.2): три пути приёма под префиксом /api/v1/partners.
    for path in (
        "/api/v1/partners/requests",
        "/api/v1/partners/requests/from-chat",
        "/api/v1/partners/requests/from-ticket",
    ):
        assert path in spec["paths"], f"missing path {path}"
        assert "post" in spec["paths"][path]


def test_intake_schemas_are_valid(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for name in ("RequestCreate", "FromChatCreate", "FromTicketCreate", "RequestRead"):
        assert name in schemas, f"missing schema {name}"
        Draft202012Validator.check_schema(schemas[name])
    # RequestRead не отдаёт ПДн-поле raw_input наружу (FR-1.6).
    assert "raw_input" not in schemas["RequestRead"]["properties"]


def test_spec_declares_lifecycle_operations(spec: dict[str, Any]) -> None:
    # M1.3: read / transition / cancel / messages под /{request_id}.
    paths = spec["paths"]
    base = "/api/v1/partners/requests"
    assert "get" in paths[base]  # список
    assert "get" in paths[f"{base}/{{request_id}}"]
    for sub in ("transition", "cancel"):
        assert "post" in paths[f"{base}/{{request_id}}/{sub}"]
    messages = paths[f"{base}/{{request_id}}/messages"]
    assert "get" in messages and "post" in messages


def test_lifecycle_schemas_are_valid(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]
    for name in (
        "RequestDetail",
        "MessageCreate",
        "MessageRead",
        "TransitionRequest",
        "CancelRequest",
        "RequestListResponse",
    ):
        assert name in schemas, f"missing schema {name}"
        Draft202012Validator.check_schema(schemas[name])
    # Карточка обязана отдавать allowed_transitions (§7, бэкенд — источник истины).
    assert "allowed_transitions" in schemas["RequestDetail"]["properties"]


def test_spec_declares_classify_operation(spec: dict[str, Any]) -> None:
    # E2 (M2.1): (ре)классификация + трассировка в карточке.
    classify = spec["paths"]["/api/v1/partners/requests/{request_id}/classify"]
    assert "post" in classify
    assert "classification" in spec["components"]["schemas"]["RequestDetail"]["properties"]


def test_spec_declares_assign_operation(spec: dict[str, Any]) -> None:
    # E3 (M2.3): подбор/назначение + объяснимость в карточке.
    assign = spec["paths"]["/api/v1/partners/requests/{request_id}/assign"]
    assert "post" in assign
    schemas = spec["components"]["schemas"]
    assert "AssignRequest" in schemas
    Draft202012Validator.check_schema(schemas["AssignRequest"])
    detail_props = schemas["RequestDetail"]["properties"]
    assert {"match_trace", "fallback_chain", "delivery_channel"} <= set(detail_props)


def test_spec_declares_dispatch_operation(spec: dict[str, Any]) -> None:
    # E4 (M3.2b): диспетчеризация.
    assert "post" in spec["paths"]["/api/v1/partners/requests/{request_id}/dispatch"]


def test_spec_declares_acceptance_operations(spec: dict[str, Any]) -> None:
    # E7 (M5.1a): приёмка + спор.
    paths = spec["paths"]
    assert "post" in paths["/api/v1/partners/requests/{request_id}/accept"]
    assert "post" in paths["/api/v1/partners/requests/{request_id}/dispute"]
    schemas = spec["components"]["schemas"]
    assert "DisputeRequest" in schemas
    Draft202012Validator.check_schema(schemas["DisputeRequest"])
    detail = schemas["RequestDetail"]["properties"]
    assert {"claim_ref", "dispute_id", "amount_ref", "escrow_ref"} <= set(detail)


def test_spec_declares_settlement_operation(spec: dict[str, Any]) -> None:
    # E7 (M5.1b): подтверждение расчёта → PAID (SERVICE).
    assert "post" in spec["paths"]["/api/v1/partners/requests/{request_id}/settlement"]
    assert "SettlementConfirm" in spec["components"]["schemas"]


def test_spec_declares_inbound_operation(spec: dict[str, Any]) -> None:
    # E5 (M3.3): подписанный webhook партнёра (публичный — security: []).
    inbound = spec["paths"]["/api/v1/partners/inbound/api/{token}"]["post"]
    assert inbound["security"] == []
    assert "InboundEnvelope" in spec["components"]["schemas"]


def test_spec_declares_channels_operations(spec: dict[str, Any]) -> None:
    # M3.2a: CRUD каналов (admin).
    paths = spec["paths"]
    assert {"get", "post"} <= set(paths["/api/v1/partners/channels"])
    assert {"get", "patch"} <= set(paths["/api/v1/partners/channels/{config_id}"])
    schemas = spec["components"]["schemas"]
    for name in ("ChannelConfigCreate", "ChannelConfigUpdate", "ChannelConfigRead", "ChannelType"):
        assert name in schemas, f"missing schema {name}"
        Draft202012Validator.check_schema(schemas[name])
    # inbound_token (секрет) не возвращается наружу.
    assert "inbound_token" not in schemas["ChannelConfigRead"]["properties"]
