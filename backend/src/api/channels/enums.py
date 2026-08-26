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


class ChannelRole(str, enum.Enum):
    """Роль канала в доставке (ADR-0006). Ортогональна `priority`.

    PRIMARY — участвует в переборе фолбэка: каналы пробуются по возрастанию priority,
    перебор останавливается на первом успехе. DUPLICATE — в переборе НЕ участвует и
    получает копию заявки после успешной основной доставки.

    Приоритет отвечает на вопрос «в каком порядке пробовать», роль — «вместо или
    вдобавок»; одним полем это не выражается: `priority=2` не значит «всегда».
    """

    PRIMARY = "PRIMARY"
    DUPLICATE = "DUPLICATE"


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
