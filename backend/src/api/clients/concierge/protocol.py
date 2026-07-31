"""Интерфейс клиента Консьержа: исходящий колбэк смены статуса (E9, U3, issue #7)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ConciergeClient(Protocol):
    async def deliver_status_update(self, payload: dict[str, Any]) -> bool:
        """Доставить колбэк смены статуса в inbound-эндпоинт Консьержа (идемпотентно).

        `True` при 2xx; недоступность соседа → `ExternalServiceError` (ретрай на дрейне).
        """
        ...
