"""Юнит-тесты Dramatiq-обвязки: брокер config-gated, актор зарегистрирован."""

from __future__ import annotations

import dramatiq
from dramatiq.brokers.stub import StubBroker


def test_broker_is_stub_without_url() -> None:
    from api.tasks.broker import broker

    assert isinstance(broker, StubBroker)  # пустой worker_broker_url → инертно


def test_drain_actor_registered() -> None:
    from api.tasks.actors import drain_outbox_dispatch

    assert isinstance(drain_outbox_dispatch, dramatiq.Actor)
    assert drain_outbox_dispatch.actor_name == "drain_outbox_dispatch"
