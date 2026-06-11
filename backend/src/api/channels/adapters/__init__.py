"""Адаптеры каналов доставки (§9.2). Реальные SDK (Telegram/MAX/CRM/SMTP) — через ADR."""

from __future__ import annotations

from api.channels.adapters.mock import MockChannel
from api.channels.adapters.partner_api import PartnerApiChannel

__all__ = ["MockChannel", "PartnerApiChannel"]
