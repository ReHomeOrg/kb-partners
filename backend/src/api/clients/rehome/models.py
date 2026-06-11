"""DTO платёжного контура rehome.one (E7, FR-7.3). Только ссылки, не суммы."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettlementRef:
    """Ссылки контура расчёта: на сумму/escrow + наблюдаемый статус."""

    status: str
    amount_ref: str | None = None
    escrow_ref: str | None = None
