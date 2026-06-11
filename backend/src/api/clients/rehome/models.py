"""DTO контура rehome.one: расчёт (E7, FR-7.3) и контекст заявителя (E9, FR-9.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettlementRef:
    """Ссылки контура расчёта: на сумму/escrow + наблюдаемый статус. Без сумм."""

    status: str
    amount_ref: str | None = None
    escrow_ref: str | None = None


@dataclass(frozen=True)
class RequesterContext:
    """Контекст заявителя из rehome.one (User/Premises/Booking) для оператора/агента."""

    user_display_name: str | None = None
    user_phone: str | None = None
    user_email: str | None = None
    premises_address: str | None = None
    booking_status: str | None = None
