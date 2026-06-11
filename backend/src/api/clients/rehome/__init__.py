"""Клиент платёжного контура rehome.one (E7, FR-7.3).

Модуль НЕ считает суммы: триггерит расчёт/escrow/комиссию в контуре и хранит только
ссылки (`amount_ref`/`escrow_ref`). Связь по HTTP (арх-константа). Деградация → None.
"""

from __future__ import annotations

from api.clients.rehome.adapter import HttpRehomeOneClient
from api.clients.rehome.models import SettlementRef
from api.clients.rehome.protocol import RehomeOneClient

__all__ = ["RehomeOneClient", "HttpRehomeOneClient", "SettlementRef"]
