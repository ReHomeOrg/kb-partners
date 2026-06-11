"""Юнит-тесты HMAC-подписи и окна свежести входящих (E5, FR-5.2/5.4)."""

from __future__ import annotations

import hashlib
import hmac

from api.channels.inbound import is_fresh, verify_signature


def _sig(secret: str, timestamp: str, body: bytes) -> str:
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def test_verify_signature_accepts_valid() -> None:
    body, ts, secret = b'{"a":1}', "100", "s"
    assert verify_signature(body, _sig(secret, ts, body), secret, ts) is True


def test_verify_signature_rejects_tampered_and_empty_secret() -> None:
    body, ts, secret = b'{"a":1}', "100", "s"
    good = _sig(secret, ts, body)
    assert verify_signature(body, "deadbeef", secret, ts) is False
    assert verify_signature(b'{"a":2}', good, secret, ts) is False  # тело изменено
    assert verify_signature(body, good, "", ts) is False  # секрет не задан


def test_is_fresh_window() -> None:
    assert is_fresh("100", 100.0) is True
    assert is_fresh("100", 350.0) is True  # ровно на границе 300 -> ещё ок (250)
    assert is_fresh("100", 500.0) is False  # 400 > 300
    assert is_fresh("not-an-int", 100.0) is False
