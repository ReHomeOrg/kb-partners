"""Курсорная (keyset) пагинация списков заявок (§11 «списки — курсорная пагинация»).

Курсор — непрозрачная base64-строка `(<created_at iso>|<id>)`. Сортировка по
`(created_at desc, id desc)` стабильна и не «съезжает» при вставках.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import uuid

from api.errors import ProblemException

Cursor = tuple[datetime.datetime, uuid.UUID]


def encode_cursor(created_at: datetime.datetime, request_id: uuid.UUID) -> str:
    """Собрать непрозрачный курсор из ключа сортировки последнего элемента."""
    raw = f"{created_at.isoformat()}|{request_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> Cursor:
    """Разобрать курсор; некорректный → 400 (без ПДн)."""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        ts_str, id_str = raw.split("|", 1)
        return datetime.datetime.fromisoformat(ts_str), uuid.UUID(id_str)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ProblemException.bad_request(detail="Invalid pagination cursor") from exc
