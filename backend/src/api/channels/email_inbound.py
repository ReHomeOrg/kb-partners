"""IMAP-парсер входящих ответов партнёра по email (E5, FR-5.1–5.4, §9.2, ADR-0004).

«Разрабатываем сами»: IMAP через stdlib `imaplib` (в РФ-контуре, без внешних SDK).
Поток: fetch UNSEEN → распарсить номер заявки + статус из темы/тела → корреляция по
номеру → АНТИ-СПУФИНГ (from-адрес совпадает с email EMAIL-канала партнёра) → дедуп по
Message-ID (InboundEvent) → продвижение FSM (`advance_partner_status`).

Парсинг/корреляция — чистые и юнит-тестируемы; сетевой fetch инъектируется (`ImapFetcher`).
"""

from __future__ import annotations

import imaplib
import re
from collections.abc import Callable
from dataclasses import dataclass
from email import message_from_bytes
from email.utils import parseaddr
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import DISPATCH_ACTOR_ID
from api.channels.enums import ChannelType
from api.channels.models import InboundEvent, PartnerChannelConfig
from api.channels.repository import InboundRepository
from api.config import Settings
from api.observability.logging import get_logger
from api.requests.models import ServiceRequest
from api.requests.partner import advance_partner_status
from api.sla.engine import SlaPolicy

_logger = get_logger("channels.email_inbound")

_CHANNEL_PRINCIPAL = Principal(user_id=DISPATCH_ACTOR_ID, kind=PrincipalKind.SERVICE)

_NUMBER_RE = re.compile(r"\bRQ-[A-Za-z0-9-]+\b")

# Ключевые слова статуса партнёра (RU/EN) → статус (приоритет сверху вниз).
_STATUS_KEYWORDS: list[tuple[str, str]] = [
    ("отклон", "rejected"),
    ("отказ", "rejected"),
    ("reject", "rejected"),
    ("выполн", "done"),
    ("заверш", "done"),
    ("готов", "done"),
    ("done", "done"),
    ("в работ", "in_progress"),
    ("приступ", "in_progress"),
    ("progress", "in_progress"),
    ("приня", "accepted"),
    ("принят", "accepted"),
    ("accept", "accepted"),
]


@dataclass(frozen=True)
class ImapMessage:
    """Разобранное входящее письмо (минимум для корреляции)."""

    message_id: str
    from_addr: str
    subject: str
    body: str


class ImapFetcher(Protocol):
    def fetch_unseen(self) -> list[ImapMessage]: ...


def parse_number(text: str) -> str | None:
    """Извлечь номер заявки (RQ-...) из темы/тела."""
    match = _NUMBER_RE.search(text)
    return match.group(0) if match else None


def parse_status(text: str) -> str | None:
    """Сопоставить ключевые слова статусу партнёра (accepted/rejected/in_progress/done)."""
    lowered = text.lower()
    for keyword, status in _STATUS_KEYWORDS:
        if keyword in lowered:
            return status
    return None


class EmailInboundService:
    """Обработка одного входящего письма (E5): корреляция + анти-спуф + дедуп + FSM."""

    def __init__(self, session: AsyncSession, *, policy: SlaPolicy) -> None:
        self._session = session
        self._inbound = InboundRepository(session)
        self._policy = policy

    async def handle(self, message: ImapMessage) -> str:
        """Обработать письмо. Возвращает исход для логов (ok/ignored/duplicate)."""
        text = f"{message.subject}\n{message.body}"
        number = parse_number(text)
        status = parse_status(text)
        if number is None or status is None:
            return "ignored:unparseable"

        request = await self._request_by_number(number)
        if request is None or request.partner_id is None:
            return "ignored:no_request"

        config = await self._email_config(request.partner_id)
        # Анти-спуфинг: письмо принимается только с email EMAIL-канала партнёра (FR-5.4).
        sender = parseaddr(message.from_addr)[1].lower()
        if config is None or str(config.config.get("email", "")).lower() != sender:
            return "ignored:spoof"

        if await self._inbound.is_seen(config.id, message.message_id):
            return "duplicate"

        advance_partner_status(self._session, _CHANNEL_PRINCIPAL, request, status, self._policy)
        self._inbound.add_event(
            InboundEvent(
                channel_config_id=config.id, nonce=message.message_id, request_id=request.id
            )
        )
        await self._session.commit()
        _logger.info("email inbound: number=%s status=%s", number, status)
        return "ok"

    async def _request_by_number(self, number: str) -> ServiceRequest | None:
        stmt = select(ServiceRequest).where(ServiceRequest.number == number).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def _email_config(self, partner_id: str) -> PartnerChannelConfig | None:
        stmt = select(PartnerChannelConfig).where(
            PartnerChannelConfig.collaborator_id == partner_id,
            PartnerChannelConfig.channel_type == ChannelType.EMAIL,
        )
        return (await self._session.execute(stmt)).scalars().first()


class ImaplibFetcher:
    """Боевой fetcher на stdlib imaplib (IMAP4_SSL). Config-gated, блокирующий (to_thread)."""

    def __init__(
        self, settings: Settings, *, connect: Callable[..., imaplib.IMAP4] | None = None
    ) -> None:
        self._s = settings
        self._connect = connect

    def fetch_unseen(self) -> list[ImapMessage]:
        if not self._s.imap_host:
            return []
        client = self._open()
        try:
            client.select(self._s.imap_mailbox)
            typ, data = client.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                return []
            messages: list[ImapMessage] = []
            for num in data[0].split():
                typ, msg_data = client.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                messages.append(_to_message(msg_data[0][1]))
            return messages
        finally:
            with _suppress_logout():
                client.logout()

    def _open(self) -> imaplib.IMAP4:
        if self._connect is not None:
            return self._connect()
        client = imaplib.IMAP4_SSL(self._s.imap_host, self._s.imap_port)
        client.login(self._s.imap_user, self._s.imap_password)
        return client


def _to_message(raw: bytes) -> ImapMessage:
    parsed = message_from_bytes(raw)
    body = _extract_body(parsed)
    return ImapMessage(
        message_id=str(parsed.get("Message-ID", "")),
        from_addr=str(parsed.get("From", "")),
        subject=str(parsed.get("Subject", "")),
        body=body,
    )


def _extract_body(parsed: object) -> str:
    payload = getattr(parsed, "get_payload", lambda: "")()
    if isinstance(payload, list):
        return " ".join(_extract_body(part) for part in payload)
    return str(payload)


class _suppress_logout:
    """IMAP logout может бросить на уже-закрытом сокете — глушим в teardown."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return True
