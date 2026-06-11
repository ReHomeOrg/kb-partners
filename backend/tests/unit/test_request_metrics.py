"""Юнит-тесты доменных метрик жизненного цикла заявки (E6, FR-6.4)."""

from __future__ import annotations

import datetime

from prometheus_client import REGISTRY

from api.requests.enums import RequestStatus
from api.requests.metrics import record_transition


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_dispatch_records_ttfd_and_counter() -> None:
    created = datetime.datetime(2026, 6, 10, 9, tzinfo=datetime.UTC)
    at = datetime.datetime(2026, 6, 10, 10, tzinfo=datetime.UTC)
    before_ttfd = _sample("partner_request_ttfd_seconds_count")
    before_cnt = _sample("partner_request_transitions_total", {"to_status": "DISPATCHED"})
    record_transition(
        target=RequestStatus.DISPATCHED,
        at=at,
        created_at=created,
        dispatched_at=at,
        accepted_at=None,
    )
    assert _sample("partner_request_ttfd_seconds_count") == before_ttfd + 1
    assert (
        _sample("partner_request_transitions_total", {"to_status": "DISPATCHED"}) == before_cnt + 1
    )


def test_accepted_records_tta() -> None:
    dispatched = datetime.datetime(2026, 6, 10, 10, tzinfo=datetime.UTC)
    at = datetime.datetime(2026, 6, 10, 11, tzinfo=datetime.UTC)
    before = _sample("partner_request_tta_seconds_count")
    record_transition(
        target=RequestStatus.ACCEPTED,
        at=at,
        created_at=None,
        dispatched_at=dispatched,
        accepted_at=at,
    )
    assert _sample("partner_request_tta_seconds_count") == before + 1


def test_done_records_ttr() -> None:
    accepted = datetime.datetime(2026, 6, 10, 11, tzinfo=datetime.UTC)
    at = datetime.datetime(2026, 6, 10, 12, tzinfo=datetime.UTC)
    before = _sample("partner_request_ttr_seconds_count")
    record_transition(
        target=RequestStatus.DONE,
        at=at,
        created_at=None,
        dispatched_at=None,
        accepted_at=accepted,
    )
    assert _sample("partner_request_ttr_seconds_count") == before + 1


def test_non_timed_transition_only_counts() -> None:
    before = _sample("partner_request_transitions_total", {"to_status": "MATCHING"})
    record_transition(
        target=RequestStatus.MATCHING,
        at=datetime.datetime.now(datetime.UTC),
        created_at=None,
        dispatched_at=None,
        accepted_at=None,
    )
    assert _sample("partner_request_transitions_total", {"to_status": "MATCHING"}) == before + 1
