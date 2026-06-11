"""Тесты observability: маскирование ПДн, JSON-логгер, контекст."""

from __future__ import annotations

import json
import logging

from api.observability.context import bind_actor_sub, get_actor_sub, request_id_var
from api.observability.logging import JsonFormatter, configure_logging, get_logger
from api.observability.pii_mask import mask_pii


def test_mask_pii_email_phone_inn() -> None:
    masked = mask_pii("связь: ivan@example.com, +7 (916) 123-45-67, ИНН 7707083893")
    assert "ivan@example.com" not in masked
    assert "916" not in masked
    assert "7707083893" not in masked
    assert "***" in masked


def test_mask_pii_passes_through_clean_text() -> None:
    assert mask_pii("заявка на клининг квартиры") == "заявка на клининг квартиры"


def test_json_formatter_masks_event_and_includes_context() -> None:
    request_id_var.set("rid-1")
    bind_actor_sub("sub-1")
    record = logging.LogRecord(
        name="api.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="email leak ivan@example.com",
        args=(),
        exc_info=None,
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "rid-1"
    assert payload["actor_sub"] == "sub-1"
    assert "ivan@example.com" not in payload["event"]


def test_configure_logging_and_get_logger() -> None:
    configure_logging("DEBUG")
    logger = get_logger("scaffold")
    assert logger.name == "api.scaffold"
    assert get_logger("api").name == "api"
    # actor_sub доступен из контекста
    bind_actor_sub("s2")
    assert get_actor_sub() == "s2"
