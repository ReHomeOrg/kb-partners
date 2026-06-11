"""Клиент kb-support: эскалация спора → претензия COMPENSATION (E7, FR-7.2).

Связь только по HTTP (арх-константа ADR-0001). Провизорный контракт изолирован в
adapter. Деградация → None (спор всё равно открывается, claim_ref остаётся пустым —
оператор досоздаёт претензию вручную).
"""

from __future__ import annotations

from api.clients.support.adapter import HttpKbSupportClient
from api.clients.support.models import ClaimRef
from api.clients.support.protocol import KbSupportClient

__all__ = ["KbSupportClient", "HttpKbSupportClient", "ClaimRef"]
