"""HTTP-клиент Консьержа (E9, U3, issue #7) поверх resilient-фундамента.

SERVICE-only inbound-контракт Консьержа изолирован здесь: `POST
/api/v1/concierge/inbound/status-update` тело `{session_id, text, ref?, status?}`
(m2m Bearer, ADR-0005). Идемпотентность — заголовком. `text` — нейтральная RU-сводка
без ПДн (собрана эмиттером). Тело не логируем (ФЗ-152), в WARN только operation/status.
Недоступность → `ExternalServiceError` (ретрай на дрейне); не-2xx → False (ретрай).
"""

from __future__ import annotations

from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient

_INBOUND_PATH = "/api/v1/concierge/inbound/status-update"


class HttpConciergeClient:
    """`ConciergeClient` поверх `ResilientHttpClient` (timeout→breaker→retry)."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token = token_provider

    async def deliver_status_update(self, payload: dict[str, Any]) -> bool:
        """POST колбэка. `True` при 2xx; недоступность → `ExternalServiceError` (ретрай)."""
        token = await self._token.get_token()
        idempotency_key = f"concierge-status:{payload.get('request_id')}:{payload.get('status')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
        }
        body = {
            "session_id": payload["session_id"],
            "text": payload["text"],
            "ref": payload.get("ref"),
            "status": payload.get("status"),
        }
        response = await self._http.request(
            "POST", _INBOUND_PATH, operation="concierge_status_update", headers=headers, json=body
        )
        return response.status_code < 300
