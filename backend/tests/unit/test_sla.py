"""Юнит-тесты SLA: бизнес-часовой календарь (DST) и оценка состояния (E6)."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from api.sla.calendar import BusinessCalendar
from api.sla.engine import SlaPolicy, SlaState, sla_view

_MSK = ZoneInfo("Europe/Moscow")


def _cal(open_hour: int = 9, close_hour: int = 18) -> BusinessCalendar:
    return BusinessCalendar(
        timezone="Europe/Moscow",
        open_hour=open_hour,
        close_hour=close_hour,
        business_days=frozenset({0, 1, 2, 3, 4}),
    )


def _policy(cal: BusinessCalendar, *, accept: float = 4.0, perform: float = 24.0) -> SlaPolicy:
    return SlaPolicy(calendar=cal, accept_hours=accept, perform_hours=perform, at_risk_fraction=0.8)


def test_add_within_same_business_day() -> None:
    # Среда 10:00 MSK + 4ч = 14:00 MSK.
    start = datetime.datetime(2026, 6, 10, 10, 0, tzinfo=_MSK)
    deadline = _cal().add_business_seconds(start, 4 * 3600)
    assert deadline.astimezone(_MSK) == datetime.datetime(2026, 6, 10, 14, 0, tzinfo=_MSK)


def test_add_rolls_over_to_next_business_day() -> None:
    # Среда 17:00 + 4ч: 1ч до 18:00, остаток 3ч с 9:00 четверга → 12:00 чт.
    start = datetime.datetime(2026, 6, 10, 17, 0, tzinfo=_MSK)
    deadline = _cal().add_business_seconds(start, 4 * 3600).astimezone(_MSK)
    assert deadline == datetime.datetime(2026, 6, 11, 12, 0, tzinfo=_MSK)


def test_add_skips_weekend() -> None:
    # Пятница 17:00 + 4ч: 1ч пт, остаток 3ч с 9:00 понедельника → 12:00 пн.
    start = datetime.datetime(2026, 6, 12, 17, 0, tzinfo=_MSK)  # пятница
    deadline = _cal().add_business_seconds(start, 4 * 3600).astimezone(_MSK)
    assert deadline == datetime.datetime(2026, 6, 15, 12, 0, tzinfo=_MSK)  # понедельник


def test_before_open_starts_at_open() -> None:
    start = datetime.datetime(2026, 6, 10, 7, 0, tzinfo=_MSK)  # до открытия
    deadline = _cal().add_business_seconds(start, 1 * 3600).astimezone(_MSK)
    assert deadline == datetime.datetime(2026, 6, 10, 10, 0, tzinfo=_MSK)


def test_calendar_validates_config() -> None:
    with pytest.raises(ValueError, match="business_days"):
        BusinessCalendar(timezone="UTC", open_hour=9, close_hour=18, business_days=frozenset())
    with pytest.raises(ValueError, match="open_hour"):
        BusinessCalendar(timezone="UTC", open_hour=18, close_hour=9, business_days=frozenset({0}))


def test_evaluate_states() -> None:
    policy = _policy(_cal())
    deadline = datetime.datetime(2026, 6, 10, 14, 0, tzinfo=datetime.UTC)
    start = datetime.datetime(2026, 6, 10, 10, 0, tzinfo=datetime.UTC)
    sla = {"accept_deadline": deadline.isoformat(), "accept_started_at": start.isoformat()}
    on_track = policy.evaluate(
        sla,
        deadline_key="accept_deadline",
        now=datetime.datetime(2026, 6, 10, 11, tzinfo=datetime.UTC),
    )
    at_risk = policy.evaluate(
        sla,
        deadline_key="accept_deadline",
        now=datetime.datetime(2026, 6, 10, 13, 45, tzinfo=datetime.UTC),
    )
    breached = policy.evaluate(
        sla,
        deadline_key="accept_deadline",
        now=datetime.datetime(2026, 6, 10, 15, tzinfo=datetime.UTC),
    )
    assert on_track is SlaState.ON_TRACK
    assert at_risk is SlaState.AT_RISK
    assert breached is SlaState.BREACHED


def test_evaluate_no_sla_is_on_track() -> None:
    assert (
        _policy(_cal()).evaluate(
            None, deadline_key="accept_deadline", now=datetime.datetime.now(datetime.UTC)
        )
        is SlaState.ON_TRACK
    )


def test_sla_view_met_when_stage_completed() -> None:
    policy = _policy(_cal())
    now = datetime.datetime(2026, 6, 10, 20, tzinfo=datetime.UTC)
    sla = {"accept_deadline": datetime.datetime(2026, 6, 10, 14, tzinfo=datetime.UTC).isoformat()}
    accepted = datetime.datetime(2026, 6, 10, 12, tzinfo=datetime.UTC)
    view = sla_view(sla, accepted_at=accepted, done_at=None, policy=policy, now=now)
    assert view is not None
    assert view["accept_state"] == SlaState.MET.value  # принято → этап met (хоть now > deadline)
    assert view["perform_state"] == SlaState.ON_TRACK.value  # perform_deadline ещё не задан


def test_sla_view_none_when_empty() -> None:
    assert (
        sla_view(
            None,
            accepted_at=None,
            done_at=None,
            policy=_policy(_cal()),
            now=datetime.datetime.now(datetime.UTC),
        )
        is None
    )


def test_evaluate_with_pause_extends_deadline() -> None:
    policy = _policy(_cal())
    deadline = datetime.datetime(2026, 6, 10, 14, 0, tzinfo=datetime.UTC)
    start = datetime.datetime(2026, 6, 10, 10, 0, tzinfo=datetime.UTC)
    pause = [
        datetime.datetime(2026, 6, 10, 11, tzinfo=datetime.UTC).isoformat(),
        datetime.datetime(2026, 6, 10, 13, tzinfo=datetime.UTC).isoformat(),
    ]
    sla = {
        "accept_deadline": deadline.isoformat(),
        "accept_started_at": start.isoformat(),
        "paused_intervals": [pause],
    }
    # now=15:00 > deadline 14:00, но пауза 2ч сдвигает effective → 16:00 → ещё не breached.
    state = policy.evaluate(
        sla,
        deadline_key="accept_deadline",
        now=datetime.datetime(2026, 6, 10, 15, tzinfo=datetime.UTC),
    )
    assert state is not SlaState.BREACHED
