"""Клиент Консьержа: исходящий колбэк смены статуса заявки (E9, U3, issue #7).

Связь только по HTTP (арх-константа ADR-0001). Инвертирован в inbound-эндпоинт
Консьержа. Деградация durable — через outbox (ретрай на дрейне), Консьерж недоступен →
kb-partners не падает.
"""

from __future__ import annotations

from api.clients.concierge.adapter import HttpConciergeClient
from api.clients.concierge.protocol import ConciergeClient

__all__ = ["ConciergeClient", "HttpConciergeClient"]
