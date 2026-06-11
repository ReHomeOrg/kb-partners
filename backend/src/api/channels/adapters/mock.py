"""MockChannel (§9.2) — доставка в память/лог для dev и тестов.

ТОЛЬКО dev/test (config-gated): не должен быть боевым каналом в production-сборке.
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


class MockChannel:
    """Канал-заглушка: складывает доставки в память, отдаёт синтетические события."""

    channel_type = ChannelType.MOCK

    def __init__(self) -> None:
        self.delivered: list[DeliveryPayload] = []

    async def deliver(self, payload: DeliveryPayload, config: ChannelConfig) -> DeliveryResult:
        self.delivered.append(payload)
        return DeliveryResult(
            outcome=DeliveryOutcome.SENT,
            provider_response={"mock": True},
            external_ref=f"mock:{payload.request_id}",
        )

    async def parse_inbound(
        self, payload: dict[str, Any], config: ChannelConfig
    ) -> StatusUpdate | None:
        ref = payload.get("request_ref")
        outcome = payload.get("outcome")
        if ref is None or outcome is None:
            return None
        try:
            return StatusUpdate(request_ref=str(ref), outcome=DeliveryOutcome(outcome), raw=payload)
        except ValueError:
            return None

    async def healthcheck(self, config: ChannelConfig) -> Health:
        return Health(status=HealthStatus.HEALTHY)
