"""PartnerApiChannel (§9.2) — доставка HTTP POST в API партнёра поверх resilient-клиента.

`ResilientHttpClient` инжектируется (его base_url = endpoint партнёра из конфига),
поэтому адаптер тестируется через httpx.MockTransport без сети. Идемпотентность —
заголовком `Idempotency-Key` (ключ попытки из dispatch). В тело — только
`DeliveryPayload` (минимальный состав по категории, FR-4.6); ПДн партнёру не утекают
сверх разрешённого. `provider_response` — статус/ссылка, без тела ответа партнёра.
"""

from __future__ import annotations

from typing import Any

from api.channels.enums import ChannelType, DeliveryOutcome, HealthStatus
from api.channels.protocol import (
    ChannelConfig,
    DeliveryPayload,
    DeliveryResult,
    Health,
    StatusUpdate,
)
from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError

# Маппинг статуса партнёра во входящем → исход (E5). Расширяется по мере адаптеров.
_INBOUND_STATUS: dict[str, DeliveryOutcome] = {
    "accepted": DeliveryOutcome.ACK,
    "delivered": DeliveryOutcome.DELIVERED,
    "rejected": DeliveryOutcome.FAILED,
    "failed": DeliveryOutcome.FAILED,
}


class PartnerApiChannel:
    """Канал REST/JSON к API партнёра."""

    channel_type = ChannelType.API

    def __init__(self, http: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http
        self._token = token_provider

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        path = str(config.config.get("deliver_path", "/orders"))
        token = await self._token.get_token()
        body = {
            "request_id": payload.request_id,
            "number": payload.number,
            "category": payload.category,
            "summary": payload.summary,
            "params": payload.params,
            "attachments": payload.attachments,
        }
        try:
            response = await self._http.request(
                "POST",
                path,
                operation="deliver",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": payload.idempotency_key,
                },
                json=body,
            )
        except ExternalServiceError as exc:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"error": type(exc).__name__}
            )
        if response.status_code >= 400:
            return DeliveryResult(
                outcome=DeliveryOutcome.FAILED, provider_response={"status": response.status_code}
            )
        external_ref = self._extract_ref(response)
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT,
            provider_response={"status": response.status_code},
            external_ref=external_ref,
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        ref = payload.get("external_ref") or payload.get("request_ref")
        status = payload.get("status")
        if ref is None or not isinstance(status, str):
            return None
        outcome = _INBOUND_STATUS.get(status.lower())
        if outcome is None:
            return None
        return StatusUpdate(request_ref=str(ref), outcome=outcome, raw=payload)

    async def healthcheck(self, config: ChannelConfig) -> Health:
        path = str(config.config.get("health_path", "/health"))
        try:
            response = await self._http.request("GET", path, operation="healthcheck")
        except ExternalServiceError:
            return Health(status=HealthStatus.UNHEALTHY, detail="unreachable")
        if response.status_code >= 400:
            return Health(status=HealthStatus.DEGRADED, detail=f"status={response.status_code}")
        return Health(status=HealthStatus.HEALTHY)

    @staticmethod
    def _extract_ref(response: Any) -> str | None:
        try:
            data = response.json()
        except ValueError:
            return None
        ref = data.get("external_ref") if isinstance(data, dict) else None
        return str(ref) if ref is not None else None
