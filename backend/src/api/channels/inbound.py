"""Приём ответов партнёра (эпик E5, FR-5.1–5.4).

Инварианты (критичный модуль): входящие принимаются только при валидной HMAC-подписи
и свежем таймстемпе (replay-защита); дубль по nonce → no-op (идемпотентность);
партнёр может двигать ТОЛЬКО свои назначенные заявки (анти-спуфинг). Статусы
маппятся на FSM ServiceRequest; ответ партнёра — `RequestMessage(author_type=partner)`.

M3.3 реализует контур `POST /inbound/api/{token}` (подписанный webhook). Каналы
CRM/Telegram/MAX/IMAP используют тот же InboundService с разбором своего формата.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.auth.system_actors import DISPATCH_ACTOR_ID
from api.channels.models import InboundEvent
from api.channels.repository import InboundRepository
from api.channels.schemas import InboundEnvelope
from api.errors import ProblemException
from api.observability.logging import get_logger
from api.requests.enums import AuthorType, RequestStatus
from api.requests.models import RequestMessage, ServiceRequest
from api.requests.service import apply_transition

_logger = get_logger("inbound")

# Окно свежести таймстемпа (сек) — защита от replay старых сообщений.
_TIMESTAMP_WINDOW = 300

# Партнёрский статус → целевой статус FSM (§7, FR-5.3). Отклонение → MATCHING
# (возврат в пул, авто-fallback к следующему партнёру — веха M4/E6).
_STATUS_TARGET: dict[str, RequestStatus] = {
    "accepted": RequestStatus.ACCEPTED,
    "rejected": RequestStatus.MATCHING,
    "in_progress": RequestStatus.IN_PROGRESS,
    "done": RequestStatus.DONE,
}

# Системный субъект для атрибуции FSM-переходов, инициированных входящим (канал).
_CHANNEL_PRINCIPAL = Principal(user_id=DISPATCH_ACTOR_ID, kind=PrincipalKind.SERVICE)


def verify_signature(raw_body: bytes, signature: str, secret: str, timestamp: str) -> bool:
    """Сверить HMAC-SHA256(`<timestamp>.<body>`, secret) с подписью (constant-time)."""
    if not secret:
        return False
    message = timestamp.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def is_fresh(timestamp: str, now: float, window: int = _TIMESTAMP_WINDOW) -> bool:
    """Таймстемп в пределах окна (replay-защита)."""
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    return abs(now - ts) <= window


class InboundService:
    """Обработка входящих от партнёра по подписанному каналу (E5)."""

    def __init__(self, session: AsyncSession, *, now: Callable[[], float] = time.time) -> None:
        self._session = session
        self._repo = InboundRepository(session)
        self._now = now

    async def handle_api(
        self, *, token: str, raw_body: bytes, signature: str, timestamp: str
    ) -> dict[str, str]:
        config = await self._repo.config_by_inbound_token(token)
        if config is None:
            raise ProblemException.not_found()
        if not is_fresh(timestamp, self._now()) or not verify_signature(
            raw_body, signature, config.inbound_token or "", timestamp
        ):
            raise ProblemException.unauthorized(detail="Invalid signature or timestamp")

        envelope = self._parse(raw_body)

        # Дедуп/replay: повтор nonce — no-op (состояние не меняем повторно, FR-5.4).
        if await self._repo.is_seen(config.id, envelope.nonce):
            return {"status": "duplicate"}

        request = await self._correlate(envelope.request_ref)
        # Анти-спуфинг: партнёр двигает только свои назначенные заявки.
        if request is None or request.partner_id != config.collaborator_id:
            raise ProblemException.not_found()

        self._advance_status(request, envelope.status)
        if envelope.message is not None:
            self._session.add(
                RequestMessage(
                    request_id=request.id,
                    author_type=AuthorType.PARTNER,
                    author_id=config.collaborator_id,
                    is_internal=False,
                    text=envelope.message,
                )
            )
        self._repo.add_event(
            InboundEvent(channel_config_id=config.id, nonce=envelope.nonce, request_id=request.id)
        )
        await self._session.commit()
        _logger.info(
            "inbound processed: number=%s partner_status=%s status=%s",
            request.number,
            envelope.status,
            request.status.value,
        )
        return {"status": "ok"}

    @staticmethod
    def _parse(raw_body: bytes) -> InboundEnvelope:
        try:
            data = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProblemException.unprocessable(detail="Malformed inbound body") from exc
        return InboundEnvelope.model_validate(data)

    async def _correlate(self, request_ref: str) -> ServiceRequest | None:
        try:
            request_id = uuid.UUID(request_ref)
        except ValueError:
            return None
        stmt = select(ServiceRequest).where(ServiceRequest.id == request_id).with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    def _advance_status(self, request: ServiceRequest, partner_status: str) -> None:
        target = _STATUS_TARGET.get(partner_status.lower())
        if target is None:
            raise ProblemException.unprocessable(detail=f"Unknown partner status: {partner_status}")
        if target is request.status:
            return  # уже в целевом статусе — идемпотентно
        apply_transition(self._session, _CHANNEL_PRINCIPAL, request, target)
