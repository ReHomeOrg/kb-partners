"""HTTP-реализация клиента rehome.one (E7, FR-7.3) поверх resilient-фундамента.

Провизорный контракт платёжного контура (ADR-0006) изолирован здесь. Модуль НЕ
считает суммы — только триггерит и хранит ссылки. Идемпотентность — заголовком.
"""

from __future__ import annotations

import json
from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.rehome.models import SettlementRef
from api.observability.logging import get_logger

_logger = get_logger("clients.rehome")

_SETTLEMENTS_PATH = "/api/v1/settlements"


class HttpRehomeOneClient:
    """`RehomeOneClient` поверх `ResilientHttpClient`."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token = token_provider

    async def trigger_settlement(
        self, *, request_id: str, service_order_id: str | None, idempotency_key: str
    ) -> SettlementRef | None:
        token = await self._token.get_token()
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key}
        body = {"request_id": request_id, "service_order_id": service_order_id}
        try:
            response = await self._http.request(
                "POST",
                _SETTLEMENTS_PATH,
                operation="trigger_settlement",
                headers=headers,
                json=body,
            )
        except ExternalServiceError as exc:
            _logger.warning("rehome trigger_settlement degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("rehome trigger_settlement degraded: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return SettlementRef(
                status=str(payload["status"]),
                amount_ref=payload.get("amount_ref"),
                escrow_ref=payload.get("escrow_ref"),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            _logger.warning("rehome trigger_settlement degraded: malformed JSON")
            return None
