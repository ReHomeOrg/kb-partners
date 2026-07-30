"""DTO клиента kb-files (вложения заявок, #5)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileMetadata:
    """Авторитетные метаданные вложения из kb-files (байты — там, тут только ссылка)."""

    file_id: str
    owner_scope: str
    content_type: str
    size_bytes: int
    filename: str | None


@dataclass(frozen=True)
class DownloadUrl:
    """Presigned-ссылка на скачивание вложения с ограниченным TTL."""

    url: str
    expires_in_seconds: int
