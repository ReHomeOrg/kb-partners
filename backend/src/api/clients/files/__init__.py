"""Клиент kb-files: вложения (фото) к заявке (#5).

Связь только по HTTP (арх-константа ADR-0001). kb-files — владелец объектного
хранилища (MinIO/S3) и presigned-URL; kb-partners хранит только `file_id`.
Деградация → None (сообщение всё равно постится, вложение помечается непроверенным,
download-URL не выдаётся — fail-safe против выдачи ссылок на чужие/несуществующие файлы).
"""

from __future__ import annotations

from api.clients.files.adapter import HttpKbFilesClient
from api.clients.files.models import DownloadUrl, FileMetadata
from api.clients.files.protocol import KbFilesClient

__all__ = ["KbFilesClient", "HttpKbFilesClient", "FileMetadata", "DownloadUrl"]
