"""Интерфейс клиента контура rehome.one (расчёт E7 + контекст заявителя E9)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.rehome.models import RequesterContext, SettlementRef


@runtime_checkable
class RehomeOneClient(Protocol):
    async def trigger_settlement(
        self, *, request_id: str, service_order_id: str | None, idempotency_key: str
    ) -> SettlementRef | None:
        """Запустить расчёт/escrow в контуре (идемпотентно). `None` при недоступности."""
        ...

    async def get_requester_context(
        self, *, requester_id: str, premises_id: str | None, booking_id: str | None
    ) -> RequesterContext | None:
        """Контекст заявителя (User/Premises/Booking). `None` при недоступности."""
        ...
