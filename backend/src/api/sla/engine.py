"""SLA-движок (E6, FR-6.1/6.2): постановка дедлайнов и оценка состояния на чтении.

`sla` JSONB заявки (§6.1): {accept_deadline, perform_deadline, paused_intervals,
breach_flags, sla_state}. Дедлайны ставятся при переходах (диспетчеризация/принятие),
breach/состояние — вычисляются на чтении (без воркера).
"""

from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass
from typing import Any

from api.config import Settings
from api.sla.calendar import BusinessCalendar


class SlaState(str, enum.Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    MET = "MET"  # этап завершён в срок (дедлайн снят)


@dataclass(frozen=True)
class SlaPolicy:
    """Политика SLA из конфигурации (бизнес-часы + длительности этапов)."""

    calendar: BusinessCalendar
    accept_hours: float
    perform_hours: float
    at_risk_fraction: float

    @classmethod
    def from_settings(cls, settings: Settings) -> SlaPolicy:
        return cls(
            calendar=BusinessCalendar(
                timezone=settings.sla_timezone,
                open_hour=settings.sla_business_open_hour,
                close_hour=settings.sla_business_close_hour,
                business_days=frozenset(settings.sla_business_days),
            ),
            accept_hours=settings.sla_accept_hours,
            perform_hours=settings.sla_perform_hours,
            at_risk_fraction=settings.sla_at_risk_fraction,
        )

    def set_accept_deadline(
        self, sla: dict[str, Any] | None, dispatched_at: datetime.datetime
    ) -> dict[str, Any]:
        """Поставить дедлайн принятия = dispatched_at + accept_hours (бизнес)."""
        updated = dict(sla or {})
        deadline = self.calendar.add_business_seconds(dispatched_at, self.accept_hours * 3600)
        updated["accept_deadline"] = deadline.isoformat()
        updated.setdefault("paused_intervals", [])
        return updated

    def set_perform_deadline(
        self, sla: dict[str, Any] | None, accepted_at: datetime.datetime
    ) -> dict[str, Any]:
        """Поставить дедлайн выполнения = accepted_at + perform_hours (бизнес)."""
        updated = dict(sla or {})
        deadline = self.calendar.add_business_seconds(accepted_at, self.perform_hours * 3600)
        updated["perform_deadline"] = deadline.isoformat()
        updated.setdefault("paused_intervals", [])
        return updated

    def evaluate(
        self, sla: dict[str, Any] | None, *, deadline_key: str, now: datetime.datetime
    ) -> SlaState:
        """Состояние этапа по его дедлайну на момент `now` (с учётом пауз)."""
        if not sla:
            return SlaState.ON_TRACK
        raw = sla.get(deadline_key)
        if not isinstance(raw, str):
            return SlaState.ON_TRACK
        deadline = datetime.datetime.fromisoformat(raw)
        paused = _paused_seconds(sla.get("paused_intervals"))
        effective = deadline + datetime.timedelta(seconds=paused)
        if now >= effective:
            return SlaState.BREACHED
        total = (effective - _stage_start(sla, deadline_key, deadline)).total_seconds()
        elapsed = (now - _stage_start(sla, deadline_key, deadline)).total_seconds()
        if total > 0 and elapsed / total >= self.at_risk_fraction:
            return SlaState.AT_RISK
        return SlaState.ON_TRACK


def sla_view(
    sla: dict[str, Any] | None,
    *,
    accepted_at: datetime.datetime | None,
    done_at: datetime.datetime | None,
    policy: SlaPolicy,
    now: datetime.datetime,
) -> dict[str, Any] | None:
    """Обогатить `sla` вычисленными на чтении состояниями этапов (FR-6.2)."""
    if not sla:
        return None
    view = dict(sla)
    view["accept_state"] = (
        SlaState.MET.value
        if accepted_at is not None
        else policy.evaluate(sla, deadline_key="accept_deadline", now=now).value
    )
    if done_at is not None:
        view["perform_state"] = SlaState.MET.value
    elif accepted_at is not None:
        view["perform_state"] = policy.evaluate(sla, deadline_key="perform_deadline", now=now).value
    else:
        view["perform_state"] = SlaState.ON_TRACK.value
    return view


def _paused_seconds(intervals: Any) -> float:
    """Суммарная длительность пауз (ожидание пользователя/третьей стороны) в секундах."""
    if not isinstance(intervals, list):
        return 0.0
    total = 0.0
    for item in intervals:
        if isinstance(item, list) and len(item) == 2:
            try:
                start = datetime.datetime.fromisoformat(str(item[0]))
                end = datetime.datetime.fromisoformat(str(item[1]))
            except ValueError:
                continue
            total += max(0.0, (end - start).total_seconds())
    return total


def _stage_start(
    sla: dict[str, Any], deadline_key: str, deadline: datetime.datetime
) -> datetime.datetime:
    """Старт этапа для оценки AT_RISK; при отсутствии — приблизим как дедлайн минус сутки."""
    start_key = "accept_started_at" if deadline_key == "accept_deadline" else "perform_started_at"
    raw = sla.get(start_key)
    if isinstance(raw, str):
        return datetime.datetime.fromisoformat(raw)
    return deadline - datetime.timedelta(days=1)
