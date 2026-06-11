"""Юнит-тесты ORM-моделей ядра заявки (структура схемы, без БД).

Проверяют, что таблицы зарегистрированы в Base.metadata и несут ключевые поля и
инварианты-на-уровне-схемы (NOT NULL actor_id, частичный unique idempotency_key,
FK на service_requests). Поведенческие тесты с реальной БД — в integration (M1.2+).
"""

from __future__ import annotations

from api.db.base import Base
from api.requests.models import RequestHistory, RequestMessage, ServiceRequest


def test_tables_registered() -> None:
    tables = set(Base.metadata.tables)
    assert {"service_requests", "request_messages", "request_history"} <= tables


def test_service_request_has_core_columns() -> None:
    cols = ServiceRequest.__table__.columns
    for name in (
        "id",
        "number",
        "requester_id",
        "channel_in",
        "raw_input",
        "raw_input_masked",
        "category",
        "status",
        "access_level",
        "idempotency_key",
    ):
        assert name in cols, name
    assert cols["raw_input"].nullable is False
    assert cols["raw_input_masked"].nullable is False
    assert cols["number"].unique is True


def test_idempotency_key_partial_unique_index() -> None:
    table = Base.metadata.tables["service_requests"]
    matches = [i for i in table.indexes if i.name == "uq_service_requests_idempotency_key"]
    assert len(matches) == 1
    assert matches[0].unique is True


def test_request_message_is_internal_defaults_false() -> None:
    # Критичный инвариант (CLAUDE.md правило 10): заметка по умолчанию НЕ внутренняя,
    # is_internal задаётся явно. Дефолт на уровне колонки — false.
    col = RequestMessage.__table__.columns["is_internal"]
    assert col.nullable is False
    assert col.default is not None and col.default.arg is False


def test_request_message_fk_to_service_requests() -> None:
    fks = list(RequestMessage.__table__.columns["request_id"].foreign_keys)
    assert any(fk.column.table.name == "service_requests" for fk in fks)


def test_request_history_actor_id_not_null() -> None:
    # Инвариант «у каждой записи аудита есть актор» (§6.3).
    assert RequestHistory.__table__.columns["actor_id"].nullable is False
    fks = list(RequestHistory.__table__.columns["request_id"].foreign_keys)
    assert any(fk.column.table.name == "service_requests" for fk in fks)
