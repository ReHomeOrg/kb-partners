"""Тесты IMAP-парсера входящих email (E5, §9.2): parse + корреляция/анти-спуф/дедуп."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.email_inbound import (
    EmailInboundService,
    ImapMessage,
    parse_number,
    parse_status,
)
from api.channels.enums import ChannelType
from api.channels.models import PartnerChannelConfig
from api.config import Settings
from api.requests.enums import AccessLevel, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.sla.engine import SlaPolicy

_POLICY = SlaPolicy.from_settings(Settings())


def test_parse_number_and_status() -> None:
    assert parse_number("Re: заявка RQ-00000042 [CLEANING]") == "RQ-00000042"
    assert parse_number("нет номера") is None
    assert parse_status("Принял заявку, спасибо") == "accepted"
    assert parse_status("Вынужден отклонить") == "rejected"
    assert parse_status("Работа выполнена") == "done"
    assert parse_status("Приступаю, в работе") == "in_progress"
    assert parse_status("привет") is None


async def _seed(
    session: AsyncSession, *, number: str, partner_id: str, partner_email: str
) -> ServiceRequest:
    request = ServiceRequest(
        number=number,
        requester_id="u",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="уборка",
        raw_input_masked="уборка",
        status=RequestStatus.DISPATCHED,
        access_level=AccessLevel.LOGGED,
        partner_id=partner_id,
        dispatched_at=None,
        custom_fields={},
    )
    session.add(request)
    session.add(
        PartnerChannelConfig(
            collaborator_id=partner_id,
            channel_type=ChannelType.EMAIL,
            priority=10,
            config={"email": partner_email},
            is_active=True,
        )
    )
    await session.commit()
    return request


def _msg(number: str, status_text: str, from_addr: str, mid: str = "<m1@x>") -> ImapMessage:
    return ImapMessage(
        message_id=mid, from_addr=from_addr, subject=f"Re: {number}", body=status_text
    )


async def test_inbound_advances_status(session: AsyncSession) -> None:
    num = f"RQ-E-{uuid.uuid4().hex[:8]}"
    request = await _seed(session, number=num, partner_id="c-1", partner_email="c1@partner.ru")
    svc = EmailInboundService(session, policy=_POLICY)
    outcome = await svc.handle(_msg(num, "Принял заявку", "Partner <c1@partner.ru>"))
    assert outcome == "ok"
    await session.refresh(request)
    assert request.status is RequestStatus.ACCEPTED


async def test_inbound_rejects_spoofed_sender(session: AsyncSession) -> None:
    num = f"RQ-E-{uuid.uuid4().hex[:8]}"
    request = await _seed(session, number=num, partner_id="c-1", partner_email="c1@partner.ru")
    svc = EmailInboundService(session, policy=_POLICY)
    outcome = await svc.handle(_msg(num, "Принял", "evil@attacker.ru"))
    assert outcome == "ignored:spoof"
    await session.refresh(request)
    assert request.status is RequestStatus.DISPATCHED  # не изменён


async def test_inbound_dedup_by_message_id(session: AsyncSession) -> None:
    num = f"RQ-E-{uuid.uuid4().hex[:8]}"
    await _seed(session, number=num, partner_id="c-1", partner_email="c1@partner.ru")
    svc = EmailInboundService(session, policy=_POLICY)
    first = await svc.handle(_msg(num, "Принял", "c1@partner.ru", mid="<dup@x>"))
    second = await svc.handle(_msg(num, "Принял", "c1@partner.ru", mid="<dup@x>"))
    assert first == "ok"
    assert second == "duplicate"


async def test_inbound_unparseable_ignored(session: AsyncSession) -> None:
    svc = EmailInboundService(session, policy=_POLICY)
    outcome = await svc.handle(_msg("no-number-here", "привет", "x@y.ru"))
    assert outcome == "ignored:unparseable"
