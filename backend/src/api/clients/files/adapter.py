"""HTTP-реализация клиента kb-files (#5) поверх resilient-фундамента.

Контракт kb-files изолирован здесь (арх-константа ADR-0001: связь с соседом только по
HTTP). kb-files — владелец бакета и presigned-URL; kb-partners хранит лишь `file_id`.
Деградация (недоступность/малформед/4xx) → None: вложение помечается непроверенным,
основной поток сообщений не блокируется.
"""

from __future__ import annotations

import json
from typing import Any

from api.clients.auth import TokenProvider
from api.clients.base import ResilientHttpClient
from api.clients.errors import ExternalServiceError
from api.clients.files.models import DownloadUrl, FileMetadata
from api.observability.logging import get_logger

_logger = get_logger("clients.files")

_FILES_PATH = "/api/v1/files"


class HttpKbFilesClient:
    """`KbFilesClient` поверх `ResilientHttpClient`."""

    def __init__(self, *, http_client: ResilientHttpClient, token_provider: TokenProvider) -> None:
        self._http = http_client
        self._token = token_provider

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._token.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def get_metadata(self, file_id: str) -> FileMetadata | None:
        try:
            response = await self._http.request(
                "GET",
                f"{_FILES_PATH}/{file_id}",
                operation="get_metadata",
                headers=await self._auth_headers(),
            )
        except ExternalServiceError as exc:
            _logger.warning("files get_metadata degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("files get_metadata degraded: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return FileMetadata(
                file_id=str(payload["id"]),
                owner_scope=str(payload["owner_scope"]),
                content_type=str(payload["content_type"]),
                size_bytes=int(payload["size_bytes"]),
                filename=(
                    str(payload["filename"]) if payload.get("filename") is not None else None
                ),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            _logger.warning("files get_metadata degraded: malformed JSON")
            return None

    async def get_download_url(self, file_id: str) -> DownloadUrl | None:
        try:
            response = await self._http.request(
                "GET",
                f"{_FILES_PATH}/{file_id}/download-url",
                operation="get_download_url",
                headers=await self._auth_headers(),
            )
        except ExternalServiceError as exc:
            _logger.warning("files get_download_url degraded: %s", type(exc).__name__)
            return None
        if response.status_code >= 400:
            _logger.warning("files get_download_url degraded: status=%d", response.status_code)
            return None
        try:
            payload: dict[str, Any] = response.json()
            return DownloadUrl(
                url=str(payload["url"]),
                expires_in_seconds=int(payload["expires_in_seconds"]),
            )
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            _logger.warning("files get_download_url degraded: malformed JSON")
            return None
