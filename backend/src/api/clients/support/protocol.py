"""Интерфейс клиента kb-support (E7, FR-7.2)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.support.models import ClaimRef


@runtime_checkable
class KbSupportClient(Protocol):
    async def create_compensation_claim(
        self, *, request_id: str, requester_id: str, reason: str, idempotency_key: str
    ) -> ClaimRef | None:
        """Создать претензию COMPENSATION по спору (идемпотентно). `None` при недоступности."""
        ...
