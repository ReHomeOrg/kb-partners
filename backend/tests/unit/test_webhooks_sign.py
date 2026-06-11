"""Юнит-тесты подписи и маппинга событий webhooks (E8)."""

from __future__ import annotations

import hashlib
import hmac

from api.requests.enums import RequestStatus
from api.webhooks.client import sign
from api.webhooks.emitter import status_event


def test_sign_matches_hmac() -> None:
    body = b'{"event":"x"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert sign("secret", body) == expected


def test_status_event_mapping() -> None:
    assert status_event(RequestStatus.DISPATCHED) == "request.dispatched"
    assert status_event(RequestStatus.DISPUTE) == "request.dispute_opened"
    assert status_event(RequestStatus.ACCEPTED) == "request.accepted_by_partner"
    assert status_event(RequestStatus.PAID) == "request.paid"


def test_status_event_fallback() -> None:
    # Неперечисленный статус → request.<status_lower>.
    assert status_event(RequestStatus.MATCHING) == "request.matching"
