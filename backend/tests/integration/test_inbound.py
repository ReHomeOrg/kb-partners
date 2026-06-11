"""Интеграционные тесты приёма входящих от партнёра (E5, FR-5.1–5.4, acceptance E5).

Подпись/таймстемп считаются как у партнёра; каналы и заявки — реальные строки в
тест-сессии. `make_client(None)` — без JWT (inbound публичен: токен + HMAC).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.channels.enums import ChannelType
from api.channels.models import InboundEvent, PartnerChannelConfig
from api.requests.enums import AccessLevel, Category, ChannelIn, RequestStatus
from api.requests.models import RequestMessage, ServiceRequest

_TOKEN = "tok-123"
_SECRET = "tok-123"  # на M3.3 routing-токен = HMAC-секрет канала


def _url(token: str = _TOKEN) -> str:
    return f"/api/v1/partners/inbound/api/{token}"


def _signed(
    envelope: dict[str, object], *, secret: str = _SECRET, ts: int | None = None
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(envelope).encode()
    timestamp = str(ts if ts is not None else int(time.time()))
    signature = hmac.new(
        secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Signature": signature,
        "X-Timestamp": timestamp,
        "Content-Type": "application/json",
    }
    return body, headers


async def _seed_request(
    session: AsyncSession,
    *,
    partner_id: str = "c-1",
    status: RequestStatus = RequestStatus.DISPATCHED,
) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-I-{uuid.uuid4().hex[:10]}",
        requester_id="u-owner",
        channel_in=ChannelIn.WEB_FORM,
        raw_input="нужна уборка",
        raw_input_masked="нужна уборка",
        status=status,
        access_level=AccessLevel.LOGGED,
        category=Category.CLEANING,
        partner_id=partner_id,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


async def _seed_channel(
    session: AsyncSession, *, collaborator_id: str = "c-1", token: str = _TOKEN
) -> None:
    session.add(
        PartnerChannelConfig(
            collaborator_id=collaborator_id,
            channel_type=ChannelType.API,
            priority=10,
            config={},
            inbound_token=token,
            is_active=True,
        )
    )
    await session.commit()


async def test_inbound_accepted_advances_and_adds_message(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed(
        {"request_ref": str(req.id), "status": "accepted", "nonce": "n1", "message": "берём"}
    )
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.ACCEPTED
    msg = await session.scalar(select(RequestMessage).where(RequestMessage.request_id == req.id))
    assert msg is not None and msg.author_type.value == "PARTNER" and msg.text == "берём"


async def test_inbound_duplicate_nonce_is_noop(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed({"request_ref": str(req.id), "status": "accepted", "nonce": "dup"})
    client = make_client(None)
    first = await client.post(_url(), content=body, headers=headers)
    second = await client.post(_url(), content=body, headers=headers)
    assert first.json()["status"] == "ok"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    count = await session.scalar(
        select(func.count()).select_from(InboundEvent).where(InboundEvent.request_id == req.id)
    )
    assert count == 1


async def test_inbound_rejected_returns_to_matching(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed({"request_ref": str(req.id), "status": "rejected", "nonce": "n2"})
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 200
    refreshed = await session.get(ServiceRequest, req.id)
    assert refreshed is not None and refreshed.status is RequestStatus.MATCHING


async def test_inbound_bad_signature_401(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed({"request_ref": str(req.id), "status": "accepted", "nonce": "n3"})
    headers["X-Signature"] = "deadbeef"
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 401


async def test_inbound_stale_timestamp_401(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed(
        {"request_ref": str(req.id), "status": "accepted", "nonce": "n4"},
        ts=int(time.time()) - 10_000,
    )
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 401


async def test_inbound_unknown_token_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed(
        {"request_ref": str(req.id), "status": "accepted", "nonce": "n5"}, secret="other"
    )
    resp = await make_client(None).post(_url("unknown-token"), content=body, headers=headers)
    assert resp.status_code == 404


async def test_inbound_foreign_request_404(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    # Канал партнёра c-1, но заявка назначена c-2 → анти-спуфинг → 404.
    req = await _seed_request(session, partner_id="c-2")
    await _seed_channel(session, collaborator_id="c-1")
    body, headers = _signed({"request_ref": str(req.id), "status": "accepted", "nonce": "n6"})
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 404


async def test_inbound_unknown_status_422(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    req = await _seed_request(session)
    await _seed_channel(session)
    body, headers = _signed({"request_ref": str(req.id), "status": "weird", "nonce": "n7"})
    resp = await make_client(None).post(_url(), content=body, headers=headers)
    assert resp.status_code == 422
