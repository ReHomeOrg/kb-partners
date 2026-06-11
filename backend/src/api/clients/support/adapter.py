"""HTTP-реализация клиента kb-support (E7, FR-7.2) поверх resilient-фундамента.

Провизорный контракт kb-support (claims) изолирован здесь. Идемпотентность —
заголовком на m2m. `reason` — пользовательский текст: НЕ логируем тело/детали
(ФЗ-152), в WARN только operation/status. Деградация → None.
"""

from __future__ import annotations

import json
from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.support.models import ClaimRef
from api.observability.logging import get_logger

_logger = get_logger("clients.support")

_CLAIMS_PATH = "/api/v1/claims"


class HttpKbSupportClient:
    """`KbSupportClient` поверх `ResilientHttpClient`."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token = token_provider

    async def create_compensation_claim(
        self, *, request_id: str, requester_id: str, reason: str, idempotency_key: str
    ) -> ClaimRef | None:
        token = await self._token.get_token()
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key}
        body = {
            "kind": "COMPENSATION",
            "source": "kb-partners",
            "request_id": request_id,
            "requester_id": requester_id,
            "reason": reason,
        }
        try:
            response = await self._http.request(
                "POST", _CLAIMS_PATH, operation="create_claim", headers=headers, json=body
            )
        except ExternalServiceError as exc:
            _logger.warning("support create_claim degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("support create_claim degraded: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return ClaimRef(id=str(payload["id"]), status=str(payload["status"]))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            _logger.warning("support create_claim degraded: malformed JSON")
            return None
