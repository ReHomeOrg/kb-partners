"""Юнит-тесты Dramatiq-обвязки: брокер config-gated, актор зарегистрирован."""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.stub import StubBroker


def test_broker_is_stub_without_url() -> None:
    from api.tasks.broker import broker

    assert isinstance(broker, StubBroker)  # пустой worker_broker_url → инертно


def test_drain_actors_registered() -> None:
    # Имена — контракт с деплой-планировщиком (cron/периодик триггерит их по имени).
    # Концьерж-колбэк (issue #7) обязан быть в наборе, иначе PENDING копятся молча.
    from api.tasks.actors import (
        drain_outbox_concierge_callback,
        drain_outbox_dispatch,
        drain_outbox_notification,
        drain_outbox_on_create,
        drain_outbox_partner_fallback,
        drain_outbox_webhook,
    )

    for actor, name in (
        (drain_outbox_dispatch, "drain_outbox_dispatch"),
        (drain_outbox_on_create, "drain_outbox_on_create"),
        (drain_outbox_webhook, "drain_outbox_webhook"),
        (drain_outbox_notification, "drain_outbox_notification"),
        (drain_outbox_concierge_callback, "drain_outbox_concierge_callback"),
        (drain_outbox_partner_fallback, "drain_outbox_partner_fallback"),
    ):
        assert isinstance(actor, dramatiq.Actor)
        assert actor.actor_name == name
