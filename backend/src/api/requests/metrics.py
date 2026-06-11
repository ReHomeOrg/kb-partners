"""Доменные метрики жизненного цикла заявки (E6, FR-6.4).

Неймспейс `partner_request_*` (отдельно от метрик HTTP-сервера и клиентов).
TTFD — время до диспетчеризации, TTA — до принятия партнёром, TTR — до выполнения.
Лейблы низкой кардинальности (`to_status`), без ПДн. Пишутся в `apply_transition`.
"""

from __future__ import annotations

import datetime

from prometheus_client import Counter, Histogram

from api.requests.enums import RequestStatus

# Бакеты под длительности этапов (сек): минуты … несколько суток.
_DURATION_BUCKETS = (
    60.0,
    300.0,
    900.0,
    3600.0,
    4 * 3600.0,
    8 * 3600.0,
    24 * 3600.0,
    72 * 3600.0,
    7 * 24 * 3600.0,
)

REQUEST_TRANSITIONS = Counter(
    "partner_request_transitions_total",
    "Переходы статуса заявок по целевому статусу",
    ["to_status"],
)
TTFD = Histogram(
    "partner_request_ttfd_seconds",
    "Время от создания до диспетчеризации (TTFD)",
    buckets=_DURATION_BUCKETS,
)
TTA = Histogram(
    "partner_request_tta_seconds",
    "Время от диспетчеризации до принятия партнёром (TTA)",
    buckets=_DURATION_BUCKETS,
)
TTR = Histogram(
    "partner_request_ttr_seconds",
    "Время от принятия до выполнения (TTR)",
    buckets=_DURATION_BUCKETS,
)


def record_transition(
    *,
    target: RequestStatus,
    at: datetime.datetime,
    created_at: datetime.datetime | None,
    dispatched_at: datetime.datetime | None,
    accepted_at: datetime.datetime | None,
) -> None:
    """Учесть переход и длительность соответствующего этапа (FR-6.4)."""
    REQUEST_TRANSITIONS.labels(to_status=target.value).inc()
    if target is RequestStatus.DISPATCHED and created_at is not None:
        TTFD.observe((at - created_at).total_seconds())
    elif target is RequestStatus.ACCEPTED and dispatched_at is not None:
        TTA.observe((at - dispatched_at).total_seconds())
    elif target is RequestStatus.DONE and accepted_at is not None:
        TTR.observe((at - accepted_at).total_seconds())
