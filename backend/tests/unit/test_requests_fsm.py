"""Юнит-тесты машины состояний ServiceRequest (ТЗ §7)."""

from __future__ import annotations

import pytest

from api.errors import ProblemException
from api.requests.enums import RequestStatus
from api.requests.fsm import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    allowed_transitions,
    can_transition,
    ensure_transition,
    is_terminal,
)

S = RequestStatus


def test_every_status_has_entry() -> None:
    # Карта переходов полна: ни один статус не приводит к KeyError.
    assert set(ALLOWED_TRANSITIONS) == set(RequestStatus)


def test_terminal_statuses_have_no_transitions() -> None:
    expected = {S.PAID, S.CANCELLED, S.REJECTED}
    assert expected == TERMINAL_STATUSES
    for status in TERMINAL_STATUSES:
        assert allowed_transitions(status) == frozenset()
        assert is_terminal(status) is True


def test_cancelled_reachable_from_every_non_terminal() -> None:
    # «<любой нетерминальный> → CANCELLED» (§7).
    for status in RequestStatus:
        if status in TERMINAL_STATUSES:
            continue
        assert is_terminal(status) is False
        assert can_transition(status, S.CANCELLED), status


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.NEW, S.CLASSIFYING),
        (S.CLASSIFYING, S.CLASSIFIED),
        (S.CLASSIFIED, S.MATCHING),
        (S.CLASSIFIED, S.NEEDS_REVIEW),
        (S.NEEDS_REVIEW, S.MATCHING),
        (S.MATCHING, S.ASSIGNED),
        (S.ASSIGNED, S.DISPATCHED),
        (S.DISPATCHED, S.ACCEPTED),
        (S.DISPATCHED, S.MATCHING),
        (S.DISPATCHED, S.FAILED_DISPATCH),
        (S.FAILED_DISPATCH, S.MATCHING),
        (S.ACCEPTED, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.DONE),
        (S.DONE, S.ACCEPTED_BY_USER),
        (S.DONE, S.DISPUTE),
        (S.ACCEPTED_BY_USER, S.PAID),
        (S.ACCEPTED_BY_USER, S.DISPUTE),
        (S.DISPUTE, S.REJECTED),
    ],
)
def test_allowed_transitions_per_diagram(source: RequestStatus, target: RequestStatus) -> None:
    assert can_transition(source, target)
    ensure_transition(source, target)  # не должно поднимать


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (S.NEW, S.DONE),  # перескок через весь пайплайн
        (S.NEW, S.PAID),
        (S.CLASSIFIED, S.ASSIGNED),  # минуя MATCHING
        (S.MATCHING, S.DISPATCHED),  # минуя ASSIGNED
        (S.DONE, S.IN_PROGRESS),  # назад по пайплайну
        (S.PAID, S.CANCELLED),  # из терминального — нельзя
        (S.CANCELLED, S.NEW),
        (S.REJECTED, S.DISPUTE),
    ],
)
def test_forbidden_transitions_raise_conflict(source: RequestStatus, target: RequestStatus) -> None:
    assert not can_transition(source, target)
    with pytest.raises(ProblemException) as exc_info:
        ensure_transition(source, target)
    assert exc_info.value.status == 409
    # detail не содержит ПДн — только имена статусов.
    assert source.value in str(exc_info.value.detail)


def test_self_transition_forbidden() -> None:
    for status in RequestStatus:
        assert not can_transition(status, status)
