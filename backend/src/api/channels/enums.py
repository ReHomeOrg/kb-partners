"""Перечисления каналов доставки (§6.4, §6.5, §9). VARCHAR-хранение (без ALTER TYPE)."""

from __future__ import annotations

import enum


class ChannelType(str, enum.Enum):
    """Тип канала доставки партнёру (§6.4, §9.2)."""

    API = "API"
    CRM = "CRM"
    TELEGRAM = "TELEGRAM"
    MAX = "MAX"
    EMAIL = "EMAIL"
    MOCK = "MOCK"  # dev/test — только при config-gating, не в production-сборке


class DeliveryOutcome(str, enum.Enum):
    """Исход доставки / статус попытки (`DispatchAttempt.status`, §6.5)."""

    SENT = "SENT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    ACK = "ACK"  # партнёр подтвердил приём/принятие


class HealthStatus(str, enum.Enum):
    """Состояние канала по healthcheck (§9.3 — выбор среди здоровых)."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
