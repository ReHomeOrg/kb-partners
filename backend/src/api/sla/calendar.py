"""Календарь бизнес-часов (FR-6.1): прибавление рабочих секунд с учётом IANA-TZ/DST.

Рабочее окно задаётся часами открытия/закрытия (локальное время) и набором рабочих
дней недели. `add_business_seconds` шагает по дням, потребляя реальные секунды внутри
окон (границы окон — tz-aware, поэтому длительность окна на DST-день корректна).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

# Защитный горизонт перебора дней (≈5 лет) — против бесконечного цикла при пустом графике.
_MAX_DAYS = 366 * 5


@dataclass(frozen=True)
class BusinessCalendar:
    """Недельный график рабочих часов в одной таймзоне."""

    timezone: str
    open_hour: int
    close_hour: int
    business_days: frozenset[int]

    def __post_init__(self) -> None:
        if not self.business_days:
            raise ValueError("business_days must not be empty")
        if not 0 <= self.open_hour < self.close_hour <= 24:
            raise ValueError("require 0 <= open_hour < close_hour <= 24")

    def add_business_seconds(self, start: datetime.datetime, seconds: float) -> datetime.datetime:
        """Дедлайн = `start` + `seconds` рабочих секунд. Возвращает aware-UTC."""
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        tz = ZoneInfo(self.timezone)
        cursor = start.astimezone(tz)
        remaining = float(seconds)
        for _ in range(_MAX_DAYS):
            if cursor.weekday() in self.business_days:
                open_dt = cursor.replace(hour=self.open_hour, minute=0, second=0, microsecond=0)
                close_dt = self._close_of(cursor)
                segment_start = max(cursor, open_dt)
                if segment_start < close_dt:
                    available = (close_dt - segment_start).total_seconds()
                    if remaining <= available:
                        deadline = segment_start + datetime.timedelta(seconds=remaining)
                        return deadline.astimezone(datetime.UTC)
                    remaining -= available
            cursor = (cursor + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        raise ValueError("business seconds exceed the supported horizon")

    def _close_of(self, day: datetime.datetime) -> datetime.datetime:
        """Момент закрытия окна для дня `day` (24 → начало следующих суток)."""
        if self.close_hour == 24:
            return (day + datetime.timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return day.replace(hour=self.close_hour, minute=0, second=0, microsecond=0)
