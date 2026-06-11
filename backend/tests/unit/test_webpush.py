"""Юнит-тесты web-push сендера (E8, ADR-0004) — pywebpush замокан, без сети."""

from __future__ import annotations

import uuid

import pytest
from pywebpush import WebPushException

from api.config import Settings
from api.push import webpush as webpush_mod
from api.push.models import PushSubscription
from api.push.webpush import SubscriptionExpired, send_webpush

_VAPID = Settings(vapid_private_key="priv", vapid_subject="mailto:ops@rehome.one")


def _sub() -> PushSubscription:
    return PushSubscription(
        id=uuid.uuid4(),
        owner_id="u-1",
        audience="user",
        endpoint="https://push/x",
        p256dh="k",
        auth="a",
    )


async def test_inert_without_vapid_key() -> None:
    assert await send_webpush(_sub(), number="RQ-1", summary="x", settings=Settings()) is False


async def test_delivers_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_webpush(**kwargs: object) -> None:
        calls["n"] += 1

    monkeypatch.setattr(webpush_mod, "webpush", fake_webpush)
    ok = await send_webpush(_sub(), number="RQ-1", summary="Партнёр назначен", settings=_VAPID)
    assert ok is True and calls["n"] == 1


async def test_expired_subscription_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 410

    def fake_webpush(**kwargs: object) -> None:
        raise WebPushException("gone", response=_Resp())

    monkeypatch.setattr(webpush_mod, "webpush", fake_webpush)
    with pytest.raises(SubscriptionExpired):
        await send_webpush(_sub(), number="RQ-1", summary="x", settings=_VAPID)


async def test_other_error_degrades_to_false(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        status_code = 500

    def fake_webpush(**kwargs: object) -> None:
        raise WebPushException("boom", response=_Resp())

    monkeypatch.setattr(webpush_mod, "webpush", fake_webpush)
    assert await send_webpush(_sub(), number="RQ-1", summary="x", settings=_VAPID) is False
