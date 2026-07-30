"""Интеграция вложений заявки с kb-files (#5).

Проверяет обогащение и security-гейт при выдаче presigned download-URL:
- verified + download_url только если файл существует И принадлежит заявке (owner_scope);
- чужой owner_scope → verified=False, URL не выдаётся (anti-IDOR);
- неизвестный файл / недоступный kb-files → verified=False, URL нет (fail-safe);
- метаданные (тип/имя) берутся авторитетно из kb-files, не от клиента.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import Principal, PrincipalKind
from api.clients.files.models import DownloadUrl, FileMetadata
from api.main import app
from api.requests.dependencies import get_request_service
from api.requests.enums import AccessLevel, ChannelIn, RequestStatus
from api.requests.models import ServiceRequest
from api.requests.service import RequestService, attachment_owner_scope

_BASE = "/api/v1/partners/requests"


class _FakeFilesClient:
    """In-memory kb-files: известные файлы → метаданные + presigned URL."""

    def __init__(self, files: dict[str, FileMetadata]) -> None:
        self._files = files

    async def get_metadata(self, file_id: str) -> FileMetadata | None:
        return self._files.get(file_id)

    async def get_download_url(self, file_id: str) -> DownloadUrl | None:
        if file_id not in self._files:
            return None
        return DownloadUrl(url=f"https://s3.local/{file_id}?sig=test", expires_in_seconds=900)


def _principal(kind: PrincipalKind, **kwargs: Any) -> Principal:
    return Principal(user_id=uuid.uuid4(), kind=kind, **kwargs)


async def _seed(session: AsyncSession, *, requester_id: str) -> ServiceRequest:
    request = ServiceRequest(
        number=f"RQ-T-{uuid.uuid4().hex[:10]}",
        requester_id=requester_id,
        channel_in=ChannelIn.WEB_FORM,
        raw_input="Поломка, фото приложено",
        raw_input_masked="Поломка",
        status=RequestStatus.NEW,
        access_level=AccessLevel.LOGGED,
        custom_fields={},
    )
    session.add(request)
    await session.commit()
    return request


def _wire_files(session: AsyncSession, files: dict[str, FileMetadata]) -> None:
    """Подменить get_request_service сервисом с fake kb-files-клиентом на тест-сессии."""
    app.dependency_overrides[get_request_service] = lambda: RequestService(
        session, files_client=_FakeFilesClient(files)
    )


async def test_verified_attachment_gets_download_url(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    meta = FileMetadata(
        file_id="f-ok",
        owner_scope=attachment_owner_scope(req.id),
        content_type="image/jpeg",
        size_bytes=2048,
        filename="real.jpg",
    )
    _wire_files(session, {"f-ok": meta})

    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        # Клиент прислал НЕВЕРНЫЙ тип/имя — должны замениться авторитетными из kb-files.
        json={"text": "фото", "attachments": [{"file_id": "f-ok", "content_type": "text/plain"}]},
    )
    assert resp.status_code == 201, resp.text
    att = resp.json()["attachments"][0]
    assert att["verified"] is True
    assert att["content_type"] == "image/jpeg"  # авторитетно из kb-files
    assert att["filename"] == "real.jpg"
    assert att["size_bytes"] == 2048
    assert att["download_url"] == "https://s3.local/f-ok?sig=test"
    assert att["download_url_expires_in"] == 900


async def test_foreign_owner_scope_is_not_verified(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    # Файл существует, но принадлежит ДРУГОЙ заявке → нельзя выдавать URL (anti-IDOR).
    foreign = FileMetadata(
        file_id="f-foreign",
        owner_scope="partner:request:00000000-0000-0000-0000-000000000000",
        content_type="image/png",
        size_bytes=10,
        filename="stolen.png",
    )
    _wire_files(session, {"f-foreign": foreign})

    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "чужое", "attachments": [{"file_id": "f-foreign"}]},
    )
    assert resp.status_code == 201
    att = resp.json()["attachments"][0]
    assert att["verified"] is False
    assert "download_url" not in att


async def test_unknown_file_is_not_verified(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    _wire_files(session, {})  # kb-files ничего не знает

    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "нет файла", "attachments": [{"file_id": "ghost"}]},
    )
    assert resp.status_code == 201
    att = resp.json()["attachments"][0]
    assert att["verified"] is False
    assert "download_url" not in att


async def test_list_messages_resolves_attachments(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    meta = FileMetadata(
        file_id="f-ok",
        owner_scope=attachment_owner_scope(req.id),
        content_type="application/pdf",
        size_bytes=99,
        filename="doc.pdf",
    )
    _wire_files(session, {"f-ok": meta})

    await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "документ", "attachments": [{"file_id": "f-ok"}]},
    )
    resp = await make_client(owner).get(f"{_BASE}/{req.id}/messages")
    assert resp.status_code == 200
    att = resp.json()[0]["attachments"][0]
    assert att["verified"] is True
    assert att["download_url"].startswith("https://s3.local/f-ok")


async def test_without_files_client_attachment_unverified(
    make_client: Callable[..., AsyncClient], session: AsyncSession
) -> None:
    # Дефолтный get_request_service без токена kb-files → клиента нет (config-gated off).
    owner = _principal(PrincipalKind.REQUESTER)
    req = await _seed(session, requester_id=str(owner.user_id))
    resp = await make_client(owner).post(
        f"{_BASE}/{req.id}/messages",
        json={"text": "фото", "attachments": [{"file_id": "f-1"}]},
    )
    assert resp.status_code == 201
    att = resp.json()["attachments"][0]
    assert att["verified"] is False
    assert "download_url" not in att
