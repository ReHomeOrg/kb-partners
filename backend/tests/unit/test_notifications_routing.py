"""Юнит-тесты маршрутизации и seam-каналов уведомлений (E8, FR-8.1/8.2)."""

from __future__ import annotations

import uuid
from email.message import EmailMessage

import httpx

from api.clients.platform.models import CollaboratorCandidate, PartnerContact, ServiceOrderRef
from api.clients.rehome.models import RequesterContext, SettlementRef
from api.config import Settings
from api.notifications.channels import (
    NotificationNotice,
    Recipient,
    send_email,
    send_push,
    send_sms,
)
from api.notifications.contacts import NeighborContactResolver
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


async def test_channels_inert_until_configured() -> None:
    # По умолчанию каналы выключены — доставка не выполняется (нет кредов/контакта).
    off = Settings()
    notice = _notice()
    assert await send_sms(notice, "+79001112233", off) is False
    assert await send_email(notice, "u@example.com", off) is False
    assert send_push(notice, off) is False
    assert await deliver_notification(notice, Recipient(phone="+7", email="u@e.com"), off) == 0


async def test_sms_ru_delivers_when_configured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("api_id") == "id"
        assert request.url.params.get("to") == "+79001112233"
        return httpx.Response(200, json={"status": "OK", "status_code": 100})

    settings = Settings(sms_ru_api_id="id")
    notice = _notice()
    ok = await send_sms(notice, "+79001112233", settings, transport=httpx.MockTransport(handler))
    assert ok is True


async def test_sms_ru_non_ok_status_is_false() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"status": "ERROR"}))
    ok = await send_sms(_notice(), "+7", Settings(sms_ru_api_id="id"), transport=transport)
    assert ok is False


async def test_email_smtp_sends_via_injected_sender() -> None:
    sent: list[str] = []

    def fake_smtp(message: EmailMessage, settings: Settings) -> None:
        sent.append(str(message["Subject"]))

    settings = Settings(notify_smtp_host="smtp.local", notify_email_from="no-reply@rehome.one")
    ok = await send_email(_notice(), "u@example.com", settings, sender=fake_smtp)
    assert ok is True and sent and "RQ-1" in sent[0]


# --- ContactResolver (резолв ПДн-контакта по адресату) --------------------


class _FakeRehome:
    async def trigger_settlement(self, **kwargs: object) -> SettlementRef | None:
        return None

    async def get_requester_context(self, **kwargs: object) -> RequesterContext | None:
        return RequesterContext(user_phone="+79990001122", user_email="user@example.com")


class _FakePlatform:
    async def search_candidates(self, **kwargs: object) -> list[CollaboratorCandidate]:
        return []

    async def create_service_order(self, **kwargs: object) -> ServiceOrderRef | None:
        return None

    async def get_partner_contact(self, *, partner_id: str) -> PartnerContact | None:
        return PartnerContact(phone="+78887776655", email="partner@example.com")


def _resolver(settings: Settings) -> NeighborContactResolver:
    return NeighborContactResolver(
        rehome=_FakeRehome(), platform=_FakePlatform(), settings=settings
    )


async def test_resolver_user_contact_from_rehome() -> None:
    notice = NotificationNotice(
        request_id=uuid.uuid4(),
        number="RQ-1",
        audience=NotifyAudience.USER,
        summary="x",
        requester_id="u-1",
    )
    rec = await _resolver(Settings()).resolve(notice)
    assert rec.phone == "+79990001122" and rec.email == "user@example.com"


async def test_resolver_partner_contact_from_platform() -> None:
    notice = NotificationNotice(
        request_id=uuid.uuid4(),
        number="RQ-1",
        audience=NotifyAudience.PARTNER,
        summary="x",
        partner_id="c-1",
    )
    rec = await _resolver(Settings()).resolve(notice)
    assert rec.phone == "+78887776655" and rec.email == "partner@example.com"


async def test_resolver_operator_uses_config_email() -> None:
    notice = NotificationNotice(
        request_id=uuid.uuid4(), number="RQ-1", audience=NotifyAudience.OPERATOR, summary="x"
    )
    rec = await _resolver(Settings(notify_operator_email="ops@rehome.one")).resolve(notice)
    assert rec.email == "ops@rehome.one" and rec.phone is None
