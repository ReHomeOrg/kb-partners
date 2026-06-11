"""Юнит-тесты маршрутизации и seam-каналов уведомлений (E8, FR-8.1/8.2)."""

from __future__ import annotations

import uuid

from api.config import Settings
from api.notifications.channels import NotificationNotice, maybe_email, maybe_push, maybe_sms
from api.notifications.drainer import deliver_notification
from api.notifications.events import NotifyAudience, notifications_for
from api.requests.enums import RequestStatus


def _notice(audience: NotifyAudience = NotifyAudience.USER) -> NotificationNotice:
    return NotificationNotice(
        request_id=uuid.uuid4(), number="RQ-1", audience=audience, summary="Тест"
    )


def test_user_notified_on_lifecycle_milestones() -> None:
    # FR-8.1: заявителю — на ключевых вехах жизненного цикла.
    for status in (
        RequestStatus.NEW,
        RequestStatus.ASSIGNED,
        RequestStatus.ACCEPTED,
        RequestStatus.IN_PROGRESS,
        RequestStatus.DONE,
    ):
        audiences = {n.audience for n in notifications_for(status)}
        assert NotifyAudience.USER in audiences, status


def test_partner_notified_on_dispatch_and_cancel() -> None:
    # FR-8.2: партнёру — новая заявка и отмена.
    for status in (RequestStatus.DISPATCHED, RequestStatus.CANCELLED):
        assert NotifyAudience.PARTNER in {n.audience for n in notifications_for(status)}


def test_operator_escalation_on_failed_dispatch() -> None:
    # FR-4.5/9.4: эскалация оператору при провале диспетчеризации/ревью.
    assert NotifyAudience.OPERATOR in {
        n.audience for n in notifications_for(RequestStatus.FAILED_DISPATCH)
    }
    assert NotifyAudience.OPERATOR in {
        n.audience for n in notifications_for(RequestStatus.NEEDS_REVIEW)
    }


def test_intermediate_statuses_have_no_audience() -> None:
    # Технические статусы (CLASSIFYING/MATCHING) никого не уведомляют.
    assert notifications_for(RequestStatus.CLASSIFYING) == []
    assert notifications_for(RequestStatus.MATCHING) == []


def test_channels_inert_until_configured() -> None:
    # По умолчанию seam'ы выключены — попытка доставки не выполняется.
    off = Settings()
    notice = _notice()
    assert maybe_push(notice, off) is False
    assert maybe_sms(notice, off) is False
    assert maybe_email(notice, off) is False
    assert deliver_notification(notice, off) == 0


def test_channels_attempt_when_configured() -> None:
    on = Settings(notify_push_token="t", notify_sms_token="t", notify_smtp_host="smtp.local")
    notice = _notice()
    assert maybe_push(notice, on) is True
    assert maybe_sms(notice, on) is True
    assert maybe_email(notice, on) is True
    assert deliver_notification(notice, on) == 3
