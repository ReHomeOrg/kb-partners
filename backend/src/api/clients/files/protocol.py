"""Интерфейс клиента kb-files (вложения заявок, #5)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from api.clients.files.models import DownloadUrl, FileMetadata


@runtime_checkable
class KbFilesClient(Protocol):
    async def get_metadata(self, file_id: str) -> FileMetadata | None:
        """Метаданные вложения (для проверки владельца/типа). `None` — не найдено/недоступно."""
        ...

    async def get_download_url(self, file_id: str) -> DownloadUrl | None:
        """Presigned URL на скачивание. `None` — не найдено/недоступно."""
        ...
