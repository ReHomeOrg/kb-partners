"""Интерфейс клиента платёжного контура rehome.one (E7, FR-7.3)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.rehome.models import SettlementRef


@runtime_checkable
class RehomeOneClient(Protocol):
    async def trigger_settlement(
        self, *, request_id: str, service_order_id: str | None, idempotency_key: str
    ) -> SettlementRef | None:
        """Запустить расчёт/escrow в контуре (идемпотентно). `None` при недоступности."""
        ...
