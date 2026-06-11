"""Доставка исходящего webhook подписчику с HMAC-подписью (E8, §11.4)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Protocol, runtime_checkable

from api.clients.base import ResilientHttpClient


@runtime_checkable
class WebhookDelivery(Protocol):
    async def deliver(self, payload: dict[str, Any]) -> bool: ...


def sign(secret: str, body: bytes) -> str:
    """HMAC-SHA256(body, secret) в hex — заголовок X-Signature."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class WebhookClient:
    """Подписанная доставка события на endpoint подписчика поверх resilient-клиента."""

    def __init__(self, http_client: ResilientHttpClient, *, url: str, secret: str) -> None:
        self._http = http_client
        self._url = url
        self._secret = secret

    async def deliver(self, payload: dict[str, Any]) -> bool:
        """Доставить событие. True при 2xx; недоступность → ExternalServiceError (ретрай)."""
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Signature": sign(self._secret, body),
            "X-Event": str(payload.get("event", "")),
        }
        response = await self._http.request(
            "POST", self._url, operation="deliver_webhook", content=body, headers=headers
        )
        return response.status_code < 300
